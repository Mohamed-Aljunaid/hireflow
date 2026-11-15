import os
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.checkpointer import open_checkpointer, postgres_checkpointer, to_psycopg_url
from app.agents.graph import FIT_ANALYSIS, FIT_REVIEW, build_graph
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitAssessment
from app.core.config import Settings
from app.services.pipeline_runner import thread_config
from tests.fakes import BlockingLLMClient, FakeLLMClient, default_responses, sample_extraction


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://u:p@db:5432/x", "postgresql://u:p@db:5432/x"),
        ("postgresql+psycopg://u:p@h/x", "postgresql://u:p@h/x"),
        ("postgresql://u:p@h/x", "postgresql://u:p@h/x"),
        ("sqlite+aiosqlite:///:memory:", None),
    ],
)
def test_to_psycopg_url(url: str, expected: str | None) -> None:
    assert to_psycopg_url(url) == expected


async def test_non_postgres_url_uses_in_memory(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    async with open_checkpointer(settings) as saver:
        assert isinstance(saver, InMemorySaver)
    assert "will NOT survive a restart" in caplog.text


@pytest.mark.postgres
@pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="TEST_DATABASE_URL not set")
async def test_postgres_state_survives_reconnect() -> None:
    """Real AsyncPostgresSaver: crash mid-run, reconnect with a new pool, resume."""
    conninfo = to_psycopg_url(os.environ["TEST_DATABASE_URL"])
    assert conninfo is not None
    settings = Settings(_env_file=None)
    config = thread_config(uuid.uuid4())
    state = {
        "application_id": "pg-test",
        "cv": ParsedCV.from_extraction(sample_extraction()).model_dump(mode="json"),
        "job_text": "Senior Python Engineer posting",
    }

    import asyncio

    llm_a = BlockingLLMClient(block_on=FitAssessment, responses=default_responses())
    async with postgres_checkpointer(conninfo) as saver:
        graph = build_graph(llm_a, settings).compile(checkpointer=saver)
        task = asyncio.create_task(graph.ainvoke(state, config, durability="sync"))
        await llm_a.reached.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    llm_b = FakeLLMClient(responses=default_responses())
    async with postgres_checkpointer(conninfo) as saver:
        graph = build_graph(llm_b, settings).compile(checkpointer=saver)
        snapshot = await graph.aget_state(config)
        assert tuple(snapshot.next) == (FIT_ANALYSIS,)
        assert "job" in snapshot.values
        await graph.ainvoke(None, config, durability="sync")  # runs fit, pauses at the gate
        assert tuple((await graph.aget_state(config)).next) == (FIT_REVIEW,)

    # Process C approves the paused run over yet another pool.
    async with postgres_checkpointer(conninfo) as saver:
        graph = build_graph(FakeLLMClient(), settings).compile(checkpointer=saver)
        final = await graph.ainvoke(Command(resume={"action": "approve"}), config)
        assert (await graph.aget_state(config)).next == ()

    assert final["fit_report"]["overall_score"] == 71
    assert final["reviews"][0]["action"] == "approve"
    assert [c.output_model for c in llm_b.calls] == [FitAssessment]
