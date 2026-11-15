import uuid

from fastapi import APIRouter, HTTPException, status

from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.api.deps import RunnerDep, SessionDep, SettingsDep
from app.api.schemas import ApplicationCreate, ApplicationRead
from app.db.models import Application
from app.services import application_repository as apps
from app.services import cv_repository
from app.services.pipeline_runner import PipelineRunner

router = APIRouter(prefix="/applications", tags=["applications"])


async def _read(application: Application, runner: PipelineRunner) -> ApplicationRead:
    snapshot = await runner.snapshot(application.id)
    values = snapshot.values or {}
    return ApplicationRead(
        id=application.id,
        cv_id=application.cv_id,
        status=application.status,
        error=application.error,
        created_at=application.created_at,
        updated_at=application.updated_at,
        next_steps=list(snapshot.next),
        job=JobPosting.model_validate(values["job"]) if "job" in values else None,
        fit_report=(
            FitReport.model_validate(values["fit_report"]) if "fit_report" in values else None
        ),
    )


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
    application = await apps.get_application(session, app_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return await _read(application, runner)
