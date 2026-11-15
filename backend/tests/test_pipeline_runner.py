import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import FIT_ANALYSIS, PARSE_JOB, build_graph
from app.agents.schemas.fit import FitAssessment, FitReport
from app.agents.schemas.job import JobPostingExtraction
from app.core.config import Settings
from app.core.llm import LLMRefusalError
from app.services import application_repository as apps
from app.services.pipeline_runner import PipelineRunner, thread_config
from tests.fakes import BlockingLLMClient, FakeLLMClient, default_responses, seed_application

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


def make_runner(llm, settings: Settings, factory: Factory, checkpointer=None) -> PipelineRunner:
    graph = build_graph(llm, settings).compile(checkpointer=checkpointer or InMemorySaver())
    return PipelineRunner(graph, factory)


async def status_of(factory: Factory, app_id: uuid.UUID) -> tuple[str, str | None]:
    async with factory() as session:
        application = await apps.get_application(session, app_id)
        assert application is not None
        return application.status, application.error


async def test_run_completes_and_records_status(
    session_factory: Factory, settings: Settings
) -> None:
    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await seed_application(session_factory)

    await runner.start(app_id)
    assert runner.is_active(app_id)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    assert not runner.is_active(app_id)
    snapshot = await runner.snapshot(app_id)
    assert snapshot.next == ()
    assert FitReport.model_validate(snapshot.values["fit_report"]).overall_score == 71
    assert snapshot.values["application_id"] == str(app_id)


async def test_llm_failure_marks_failed_with_message(
    session_factory: Factory, settings: Settings
) -> None:
    responses = default_responses()
    responses[JobPostingExtraction] = LLMRefusalError("model refused the request")
    runner = make_runner(FakeLLMClient(responses=responses), settings, session_factory)
    app_id = await seed_application(session_factory)

    await runner.start(app_id)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("failed", "model refused the request")


async def test_unexpected_error_is_not_leaked(session_factory: Factory, settings: Settings) -> None:
    responses = default_responses()
    responses[FitAssessment] = RuntimeError("secret internals")
    runner = make_runner(FakeLLMClient(responses=responses), settings, session_factory)
    app_id = await seed_application(session_factory)

    await runner.start(app_id)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("failed", "internal error: RuntimeError")


async def test_start_unknown_application_raises(
    session_factory: Factory, settings: Settings
) -> None:
    runner = make_runner(FakeLLMClient(), settings, session_factory)
    with pytest.raises(LookupError):
        await runner.start(uuid.uuid4())


async def test_resume_after_restart_continues_from_checkpoint(
    session_factory: Factory, settings: Settings, tmp_path: Path
) -> None:
    """The Phase 3 guarantee: state survives a process restart and the run resumes.

    Process A dies during fit_analysis (task cancelled). Process B opens a new
    checkpointer on the same database, resumes, and must not re-run parse_job.
    """
    checkpoint_db = str(tmp_path / "checkpoints.sqlite")
    app_id = await seed_application(session_factory)

    # --- process A ---
    llm_a = BlockingLLMClient(block_on=FitAssessment, responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_a:
        runner_a = make_runner(llm_a, settings, session_factory, saver_a)
        await runner_a.start(app_id)
        await llm_a.reached.wait()  # parse_job done and checkpointed; fit in flight
        await runner_a.shutdown()  # "crash"
    assert await status_of(session_factory, app_id) == ("running", None)

    # --- process B: fresh objects, same databases ---
    llm_b = FakeLLMClient(responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_b:
        runner_b = make_runner(llm_b, settings, session_factory, saver_b)

        before = await runner_b.snapshot(app_id)
        assert tuple(before.next) == (FIT_ANALYSIS,)
        assert "job" in before.values  # persisted by process A

        assert await runner_b.resume_incomplete() == [app_id]
        await runner_b.wait(app_id)
        after = await runner_b.snapshot(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    assert [c.output_model for c in llm_b.calls] == [FitAssessment]  # parse_job not re-run
    assert after.values["job"] == before.values["job"]
    assert FitReport.model_validate(after.values["fit_report"]).overall_score == 71


async def test_resume_without_checkpoint_starts_over(
    session_factory: Factory, settings: Settings
) -> None:
    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await seed_application(session_factory)  # status running, never started

    assert await runner.resume_incomplete() == [app_id]
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    assert [c.output_model for c in llm.calls] == [JobPostingExtraction, FitAssessment]


async def test_resume_finished_run_only_fixes_status(
    session_factory: Factory, settings: Settings
) -> None:
    llm = FakeLLMClient(responses=default_responses())
    checkpointer = InMemorySaver()
    runner = make_runner(llm, settings, session_factory, checkpointer)
    app_id = await seed_application(session_factory)
    # Run the graph to the end without the runner, so the status is still "running".
    state = await runner._initial_input(app_id)
    await runner._graph.ainvoke(state, thread_config(app_id))
    calls = len(llm.calls)

    assert await runner.resume_incomplete() == []
    assert await status_of(session_factory, app_id) == ("completed", None)
    assert len(llm.calls) == calls


async def test_resume_ignores_finished_and_failed(
    session_factory: Factory, settings: Settings
) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    done, failed = await seed_application(session_factory), await seed_application(session_factory)
    async with session_factory() as session:
        await apps.set_status(session, done, "completed")
        await apps.set_status(session, failed, "failed", error="x")

    assert await runner.resume_incomplete() == []


async def test_in_flight_step_is_visible_while_running(
    session_factory: Factory, settings: Settings
) -> None:
    llm = BlockingLLMClient(block_on=JobPostingExtraction, responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await seed_application(session_factory)

    await runner.start(app_id)
    await llm.reached.wait()
    snapshot = await runner.snapshot(app_id)
    await runner.shutdown()

    assert tuple(snapshot.next) == (PARSE_JOB,)
    assert await status_of(session_factory, app_id) == ("running", None)
