import uuid

from fastapi import APIRouter, HTTPException, status

from app.agents.review import ReviewValidationError
from app.agents.schemas.review import ReviewDecision, ReviewRecord
from app.api.deps import RunnerDep, SessionDep, SettingsDep
from app.api.schemas import ApplicationCreate, ApplicationRead
from app.db.models import Application
from app.services import application_repository as apps
from app.services import cv_repository
from app.services.pipeline_runner import NotAwaitingApprovalError, PipelineRunner, pending_review

router = APIRouter(prefix="/applications", tags=["applications"])


async def _read(application: Application, runner: PipelineRunner) -> ApplicationRead:
    snapshot = await runner.snapshot(application.id)
    values = snapshot.values or {}
    # Only advertise the gate while the row says we're paused; during a resume the old
    # interrupt is still in the checkpoint until the gate node finishes.
    review = pending_review(snapshot) if application.status == "awaiting_approval" else None
    return ApplicationRead(
        id=application.id,
        cv_id=application.cv_id,
        status=application.status,
        error=application.error,
        created_at=application.created_at,
        updated_at=application.updated_at,
        next_steps=list(snapshot.next),
        pending_review=review,
        reviews=[ReviewRecord.model_validate(r) for r in values.get("reviews", [])],
        # Pydantic validates the stored dicts into the response models.
        job=values.get("job"),
        fit_report=values.get("fit_report"),
        company_brief=values.get("company_brief"),
        tailored=values.get("tailored"),
        cover_letter=values.get("cover_letter"),
    )


async def _get_or_404(session: SessionDep, app_id: uuid.UUID) -> Application:
    application = await apps.get_application(session, app_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return application


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_application(
    body: ApplicationCreate, session: SessionDep, runner: RunnerDep, settings: SettingsDep
) -> ApplicationRead:
    """Create an application and start its pipeline in the background. Poll GET for status."""
    job_text = body.job_text.strip()
    if len(job_text) > settings.max_job_posting_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"job posting exceeds {settings.max_job_posting_chars} characters",
        )
    if await cv_repository.get_cv(session, body.cv_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV not found")

    application = await apps.create_application(session, cv_id=body.cv_id, job_text=job_text)
    await runner.start(application.id)
    return await _read(application, runner)


@router.get("/{app_id}", response_model=ApplicationRead)
async def read_application(
    app_id: uuid.UUID, session: SessionDep, runner: RunnerDep
) -> ApplicationRead:
    return await _read(await _get_or_404(session, app_id), runner)


@router.post(
    "/{app_id}/resume", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED
)
async def resume_application(
    app_id: uuid.UUID, decision: ReviewDecision, session: SessionDep, runner: RunnerDep
) -> ApplicationRead:
    """Answer the pending review (approve / edit / reject); the run continues in the background.

    409 if the application is not paused at a gate; 422 if the decision does not fit it.
    """
    application = await _get_or_404(session, app_id)
    try:
        await runner.resume(app_id, decision)
    except NotAwaitingApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.refresh(application)  # the runner changed the status in its own session
    return await _read(application, runner)
