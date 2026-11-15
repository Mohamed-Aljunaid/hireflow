from fastapi import APIRouter, HTTPException, status

from app.agents.fit_analyst import analyse_fit
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.job import JobPosting
from app.api.deps import LLMDep, SessionDep, SettingsDep
from app.api.schemas import FitRequest, FitResponse
from app.services import cv_repository, job_repository

router = APIRouter(prefix="/fit", tags=["fit"])


@router.post("", response_model=FitResponse)
async def fit(
    body: FitRequest, session: SessionDep, llm: LLMDep, settings: SettingsDep
) -> FitResponse:
    """Standalone fit analysis (Phase 2). Not persisted; Phase 3 stores it per application."""
    cv = await cv_repository.get_cv(session, body.cv_id)
    if cv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV not found")
    job = await job_repository.get_job(session, body.job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    report = await analyse_fit(
        ParsedCV.model_validate(cv.parsed),
        JobPosting.model_validate(job.parsed),
        llm,
        effort=settings.anthropic_analysis_effort,
    )
    return FitResponse(cv_id=cv.id, job_id=job.id, report=report)
