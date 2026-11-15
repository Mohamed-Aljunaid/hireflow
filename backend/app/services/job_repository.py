import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas.job import JobPosting
from app.db.models import Job


async def create_job(session: AsyncSession, *, raw_text: str, parsed: JobPosting) -> Job:
    job = Job(raw_text=raw_text, parsed=parsed.model_dump(mode="json"))
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.get(Job, job_id)
