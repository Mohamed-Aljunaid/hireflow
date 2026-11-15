import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.schemas.cv import ParsedCV
from app.services import cv_repository
from tests.fakes import sample_extraction
from tests.test_migrations import alembic_config


async def _round_trip(session: AsyncSession, factory: async_sessionmaker[AsyncSession]) -> None:
    parsed = ParsedCV.from_extraction(sample_extraction())
    created = await cv_repository.create_cv(
        session, filename="cv.txt", content_type="text/plain", raw_text="raw", parsed=parsed
    )
    assert isinstance(created.id, uuid.UUID)
    assert isinstance(created.created_at, datetime)

    # Fresh session, so the read really goes to the database.
    async with factory() as other:
        loaded = await cv_repository.get_cv(other, created.id)
        assert loaded is not None
        assert loaded.raw_text == "raw"
        assert ParsedCV.model_validate(loaded.parsed) == parsed


async def test_round_trip_sqlite(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _round_trip(session, session_factory)


async def test_get_missing_returns_none(session: AsyncSession) -> None:
    assert await cv_repository.get_cv(session, uuid.uuid4()) is None


@pytest.mark.postgres
@pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="TEST_DATABASE_URL not set")
async def test_round_trip_postgres() -> None:
    """Runs the real migration against Postgres, then a JSONB round trip."""
    from alembic import command
    from starlette.concurrency import run_in_threadpool

    url = os.environ["TEST_DATABASE_URL"]
    cfg = alembic_config(url)
    await run_in_threadpool(command.downgrade, cfg, "base")
    await run_in_threadpool(command.upgrade, cfg, "head")

    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await _round_trip(session, factory)
    finally:
        await engine.dispose()
