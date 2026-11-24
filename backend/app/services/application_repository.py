import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application

ApplicationStatus = Literal["running", "awaiting_approval", "completed", "rejected", "failed"]


async def create_application(
    session: AsyncSession, *, cv_id: uuid.UUID, job_text: str, apply_url: str | None = None
) -> Application:
    application = Application(cv_id=cv_id, job_text=job_text, apply_url=apply_url, status="running")
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


async def transition(
    session: AsyncSession,
    app_id: uuid.UUID,
    from_status: ApplicationStatus,
    to_status: ApplicationStatus,
) -> bool:
    """Compare-and-set the status in one UPDATE. True if this call made the change."""
    result = await session.execute(
        update(Application)
        .where(Application.id == app_id, Application.status == from_status)
        .values(status=to_status, error=None, updated_at=datetime.now(UTC))
    )
    await session.commit()
    return result.rowcount == 1


async def list_ids_with_status(session: AsyncSession, status: ApplicationStatus) -> list[uuid.UUID]:
    result = await session.scalars(select(Application.id).where(Application.status == status))
    return list(result)
