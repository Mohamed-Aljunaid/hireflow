import asyncio
import os
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.checkpointer import open_checkpointer, postgres_checkpointer, to_psycopg_url
from app.agents.graph import CONTENT_REVIEW, FIT_ANALYSIS, FIT_REVIEW, build_graph
from app.agents.schemas.content import ClaimCheck, CoverLetterDraft, TailoringDraft
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


def _sqlite_saver(path: str):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    return lambda: AsyncSqliteSaver.from_conn_string(path)


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=[
                pytest.mark.postgres,
                pytest.mark.skipif(
                    "TEST_DATABASE_URL" not in os.environ, reason="TEST_DATABASE_URL not set"
                ),
            ],
        ),
    ]
)
def open_saver(request: pytest.FixtureRequest, tmp_path):
    """A factory that opens a *new* checkpointer connection on the same database."""
    if request.param == "sqlite":
        return _sqlite_saver(str(tmp_path / "checkpoints.sqlite"))
    conninfo = to_psycopg_url(os.environ["TEST_DATABASE_URL"])
    assert conninfo is not None
    return lambda: postgres_checkpointer(conninfo)


async def test_state_survives_reconnect_through_both_gates(open_saver) -> None:
    """Crash mid-run (A), resume on a new connection (B), answer both gates on yet
    another connection (C). Runs on SQLite always; on real Postgres in CI."""
    settings = Settings(_env_file=None)
    config = thread_config(uuid.uuid4())
    state = {
        "application_id": "reconnect-test",
        "cv": ParsedCV.from_extraction(sample_extraction()).model_dump(mode="json"),
        "job_text": "Senior Python Engineer posting",
    }

    llm_a = BlockingLLMClient(block_on=FitAssessment, responses=default_responses())
    async with open_saver() as saver:
        graph = build_graph(llm_a, settings).compile(checkpointer=saver)
        task = asyncio.create_task(graph.ainvoke(state, config, durability="sync"))
        await llm_a.reached.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    llm_b = FakeLLMClient(responses=default_responses())
    async with open_saver() as saver:
        graph = build_graph(llm_b, settings).compile(checkpointer=saver)
        snapshot = await graph.aget_state(config)
        assert tuple(snapshot.next) == (FIT_ANALYSIS,)
        assert "job" in snapshot.values and "company_brief" in snapshot.values
        await graph.ainvoke(None, config, durability="sync")  # runs fit, pauses at the gate
        assert tuple((await graph.aget_state(config)).next) == (FIT_REVIEW,)
    assert [c.output_model for c in llm_b.calls] == [FitAssessment]  # nothing before re-run

    llm_c = FakeLLMClient(responses=default_responses())
    async with open_saver() as saver:
        graph = build_graph(llm_c, settings).compile(checkpointer=saver)
        await graph.ainvoke(Command(resume={"action": "approve"}), config, durability="sync")
        assert tuple((await graph.aget_state(config)).next) == (CONTENT_REVIEW,)
        final = await graph.ainvoke(Command(resume={"action": "approve"}), config)
        assert (await graph.aget_state(config)).next == ()

    assert final["fit_report"]["overall_score"] == 71
    assert [r["gate"] for r in final["reviews"]] == [FIT_REVIEW, CONTENT_REVIEW]
    assert len(final["tailored"]["bullets"]) == 4
    assert [c.output_model for c in llm_c.calls] == [
        TailoringDraft, ClaimCheck, CoverLetterDraft, ClaimCheck
    ]  # fmt: skip
