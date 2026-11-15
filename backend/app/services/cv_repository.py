import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas.cv import ParsedCV
from app.db.models import CV


async def create_cv(
    session: AsyncSession,
    *,
    filename: str,
    content_type: str,
    raw_text: str,
    parsed: ParsedCV,
) -> CV:
    cv = CV(
        filename=filename,
        content_type=content_type,
        raw_text=raw_text,
        parsed=parsed.model_dump(mode="json"),
    )
    session.add(cv)
    await session.commit()
    await session.refresh(cv)
    return cv


async def get_cv(session: AsyncSession, cv_id: uuid.UUID) -> CV | None:
    return await session.get(CV, cv_id)
