"""Checkpointer lifecycle: Postgres in real deployments, in-memory otherwise."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings

logger = logging.getLogger(__name__)


def to_psycopg_url(database_url: str) -> str | None:
    """SQLAlchemy URL -> libpq URL for psycopg, or None if not Postgres."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url.removeprefix(prefix)
    return None


@asynccontextmanager
async def postgres_checkpointer(conninfo: str) -> AsyncIterator[AsyncPostgresSaver]:
    # Settings required by AsyncPostgresSaver (see langgraph-checkpoint-postgres docs).
    async with AsyncConnectionPool(
        conninfo,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # idempotent; creates/migrates checkpoint tables
        yield saver


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    conninfo = to_psycopg_url(settings.database_url)
    if conninfo is None:
        logger.warning(
            "DATABASE_URL is not PostgreSQL: using an in-memory checkpointer; "
            "pipeline state will NOT survive a restart."
        )
        yield InMemorySaver()
        return
    async with postgres_checkpointer(conninfo) as saver:
        yield saver
