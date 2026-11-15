from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents.schemas.cv import CVExtraction
from app.api.deps import get_llm_client
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from tests.fakes import FakeLLMClient, sample_extraction

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
    return FakeLLMClient(responses={CVExtraction: sample_extraction()})


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        max_upload_bytes=64 * 1024,
    )


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_llm: FakeLLMClient,
    test_settings: Settings,
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    app.dependency_overrides[get_settings] = lambda: test_settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
