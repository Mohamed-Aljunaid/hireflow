import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application

# Phase 4 adds "awaiting_approval" and "rejected".
ApplicationStatus = Literal["running", "completed", "failed"]


async def create_application(
    session: AsyncSession, *, cv_id: uuid.UUID, job_text: str
) -> Application:
    application = Application(cv_id=cv_id, job_text=job_text, status="running")
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def get_application(session: AsyncSession, app_id: uuid.UUID) -> Application | None:
    return await session.get(Application, app_id)


async def set_status(
    session: AsyncSession,
    app_id: uuid.UUID,
    status: ApplicationStatus,
    *,
    error: str | None = None,
) -> None:
    application = await session.get(Application, app_id)
    if application is None:
        return
    application.status = status
    application.error = error
    await session.commit()


async def list_ids_with_status(session: AsyncSession, status: ApplicationStatus) -> list[uuid.UUID]:
    result = await session.scalars(select(Application.id).where(Application.status == status))
    return list(result)
