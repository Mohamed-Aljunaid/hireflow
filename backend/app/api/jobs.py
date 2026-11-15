import uuid

from fastapi import APIRouter, HTTPException, status

from app.agents.job_parser import parse_job_posting
from app.api.deps import LLMDep, SessionDep, SettingsDep
from app.api.schemas import JobCreate, JobRead
from app.services import job_repository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate, session: SessionDep, llm: LLMDep, settings: SettingsDep
) -> JobRead:
    text = body.text.strip()
    if len(text) > settings.max_job_posting_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"job posting exceeds {settings.max_job_posting_chars} characters",
        )
    parsed = await parse_job_posting(text, llm)  # LLM errors -> 502/503
    job = await job_repository.create_job(session, raw_text=text, parsed=parsed)
    return JobRead.model_validate(job)


@router.get("/{job_id}", response_model=JobRead)
async def read_job(job_id: uuid.UUID, session: SessionDep) -> JobRead:
    job = await job_repository.get_job(session, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobRead.model_validate(job)
