import asyncio
import sys
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents.graph import build_graph
from app.agents.schemas.cv import CVExtraction
from app.agents.schemas.fit import FitAssessment
from app.agents.schemas.job import JobPostingExtraction
from app.api.deps import get_llm_client, get_runner
from app.services.pipeline_runner import PipelineRunner

if sys.platform == "win32":
    # psycopg's async mode cannot run on the default Proactor loop on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from tests.fakes import (
    FakeLLMClient,
    sample_extraction,
    sample_fit_assessment,
    sample_job_extraction,
)

SAMPLE_JOB_TEXT = """Senior Python Engineer - Northwind Labs (Remote, US)

We're hiring a senior engineer to own our backend services.

Requirements:
- 5+ years of Python backend experience
- FastAPI or similar async framework
- Kubernetes in production

Nice to have: open-source contributions.
"""

SAMPLE_CV_TEXT = """Jordan Rivera
jordan.rivera@example.com | +1 555 0100 | Austin, TX

EXPERIENCE
Senior Backend Engineer, Acme Analytics (Mar 2022 - Present)
- Led migration of a monolith to FastAPI microservices serving 2M requests/day.
- Cut p95 latency 40% by introducing Redis caching.
"""


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient(
        responses={
            CVExtraction: sample_extraction(),
            JobPostingExtraction: sample_job_extraction(),
            FitAssessment: sample_fit_assessment(),
        }
    )


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        max_upload_bytes=64 * 1024,
    )


@pytest.fixture
async def runner(
    session_factory: async_sessionmaker[AsyncSession],
    fake_llm: FakeLLMClient,
    test_settings: Settings,
) -> AsyncIterator[PipelineRunner]:
    graph = build_graph(fake_llm, test_settings).compile(checkpointer=InMemorySaver())
    r = PipelineRunner(graph, session_factory)
    yield r
    await r.shutdown()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_llm: FakeLLMClient,
    test_settings: Settings,
    runner: PipelineRunner,
) -> AsyncIterator[AsyncClient]:
    # ASGITransport does not run the lifespan, so no real checkpointer is opened.
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_runner] = lambda: runner
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
