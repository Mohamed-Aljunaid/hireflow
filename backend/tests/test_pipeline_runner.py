import asyncio
import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import FIT_ANALYSIS, FIT_REVIEW, PARSE_JOB, build_graph
from app.agents.review import ReviewValidationError
from app.agents.schemas.fit import FitAssessment, FitReport
from app.agents.schemas.job import JobPostingExtraction
from app.agents.schemas.review import MatchOverride, ReviewDecision
from app.core.config import Settings
from app.core.llm import LLMRefusalError
from app.services import application_repository as apps
from app.services.pipeline_runner import (
    NotAwaitingApprovalError,
    PipelineRunner,
    pending_review,
    thread_config,
)
from tests.fakes import BlockingLLMClient, FakeLLMClient, default_responses, seed_application

Factory = async_sessionmaker[AsyncSession]
APPROVE = ReviewDecision(action="approve")


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


async def run_to_gate(runner: PipelineRunner, factory: Factory) -> uuid.UUID:
    app_id = await seed_application(factory)
    await runner.start(app_id)
    await runner.wait(app_id)
    assert await status_of(factory, app_id) == ("awaiting_approval", None)
    return app_id


# ---------- running to the gate ----------


async def test_run_pauses_for_fit_review(session_factory: Factory, settings: Settings) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await seed_application(session_factory)

    await runner.start(app_id)
    assert runner.is_active(app_id)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("awaiting_approval", None)
    snapshot = await runner.snapshot(app_id)
    assert tuple(snapshot.next) == (FIT_REVIEW,)
    review = pending_review(snapshot)
    assert review is not None and review.gate == FIT_REVIEW
    assert FitReport.model_validate(snapshot.values["fit_report"]).overall_score == 71


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


# ---------- the three human decisions (Phase 4 done-when) ----------


async def test_approve_completes(session_factory: Factory, settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)

    await runner.resume(app_id, ReviewDecision(action="approve", feedback="Looks right"))
    assert await status_of(session_factory, app_id) == ("running", None)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    snapshot = await runner.snapshot(app_id)
    assert snapshot.next == ()
    assert snapshot.values["reviews"][0]["action"] == "approve"
    assert snapshot.values["reviews"][0]["feedback"] == "Looks right"
    assert len(llm.calls) == 2  # no LLM work re-done on resume


async def test_edit_then_continue(session_factory: Factory, settings: Settings) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)

    decision = ReviewDecision(
        action="edit",
        match_overrides=[
            MatchOverride(
                requirement_id="must-3",
                verdict="partial",
                evidence_refs=["skill-5"],
                note="Docker is adjacent to Kubernetes.",
            )
        ],
    )
    await runner.resume(app_id, decision)
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    report = FitReport.model_validate((await runner.snapshot(app_id)).values["fit_report"])
    assert report.matches[2].verdict == "partial"
    assert report.matches[2].source == "human"
    assert report.overall_score == 86


async def test_reject_stops(session_factory: Factory, settings: Settings) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)

    await runner.resume(app_id, ReviewDecision(action="reject", feedback="Not my field"))
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("rejected", None)
    snapshot = await runner.snapshot(app_id)
    assert snapshot.next == ()
    assert snapshot.values["rejection"]["feedback"] == "Not my field"


# ---------- resume guard rails ----------


async def test_invalid_edit_is_rejected_before_resuming(
    session_factory: Factory, settings: Settings
) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)
    bad = ReviewDecision(
        action="edit",
        match_overrides=[
            MatchOverride(
                requirement_id="must-3", verdict="met", evidence_refs=["k8s-cert"], note="n"
            )
        ],
    )

    with pytest.raises(ReviewValidationError, match="k8s-cert"):
        await runner.resume(app_id, bad)

    # Still paused and answerable: a bad edit never kills the run.
    assert await status_of(session_factory, app_id) == ("awaiting_approval", None)
    await runner.resume(app_id, APPROVE)
    await runner.wait(app_id)
    assert await status_of(session_factory, app_id) == ("completed", None)


async def test_resume_when_not_paused_raises(session_factory: Factory, settings: Settings) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)
    await runner.resume(app_id, APPROVE)
    await runner.wait(app_id)

    with pytest.raises(NotAwaitingApprovalError):
        await runner.resume(app_id, APPROVE)  # already completed


async def test_resume_never_started_raises(session_factory: Factory, settings: Settings) -> None:
    runner = make_runner(FakeLLMClient(), settings, session_factory)
    app_id = await seed_application(session_factory)
    with pytest.raises(NotAwaitingApprovalError):
        await runner.resume(app_id, APPROVE)


async def test_concurrent_resumes_only_one_wins(
    session_factory: Factory, settings: Settings
) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)

    results = await asyncio.gather(
        runner.resume(app_id, APPROVE),
        runner.resume(app_id, ReviewDecision(action="reject")),
        return_exceptions=True,
    )
    await runner.wait(app_id)

    assert sum(r is None for r in results) == 1
    assert sum(isinstance(r, NotAwaitingApprovalError) for r in results) == 1
    assert len((await runner.snapshot(app_id)).values["reviews"]) == 1


# ---------- restarts ----------


async def test_crash_mid_run_resumes_from_checkpoint(
    session_factory: Factory, settings: Settings, tmp_path: Path
) -> None:
    """Phase 3 guarantee: process A dies during fit_analysis; process B (new
    checkpointer on the same database) resumes without re-running parse_job."""
    checkpoint_db = str(tmp_path / "checkpoints.sqlite")
    app_id = await seed_application(session_factory)

    llm_a = BlockingLLMClient(block_on=FitAssessment, responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_a:
        runner_a = make_runner(llm_a, settings, session_factory, saver_a)
        await runner_a.start(app_id)
        await llm_a.reached.wait()
        await runner_a.shutdown()  # "crash"
    assert await status_of(session_factory, app_id) == ("running", None)

    llm_b = FakeLLMClient(responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_b:
        runner_b = make_runner(llm_b, settings, session_factory, saver_b)
        before = await runner_b.snapshot(app_id)
        assert tuple(before.next) == (FIT_ANALYSIS,)
        assert "job" in before.values

        assert await runner_b.resume_incomplete() == [app_id]
        await runner_b.wait(app_id)
        after = await runner_b.snapshot(app_id)

    assert await status_of(session_factory, app_id) == ("awaiting_approval", None)
    assert [c.output_model for c in llm_b.calls] == [FitAssessment]  # parse_job not re-run
    assert after.values["job"] == before.values["job"]


async def test_approval_after_restart(
    session_factory: Factory, settings: Settings, tmp_path: Path
) -> None:
    """Phase 4 guarantee: pause in process A, approve in process B."""
    checkpoint_db = str(tmp_path / "checkpoints.sqlite")

    llm_a = FakeLLMClient(responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_a:
        runner_a = make_runner(llm_a, settings, session_factory, saver_a)
        app_id = await run_to_gate(runner_a, session_factory)
        await runner_a.shutdown()

    llm_b = FakeLLMClient(responses=default_responses())
    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver_b:
        runner_b = make_runner(llm_b, settings, session_factory, saver_b)
        # Startup recovery must leave a paused run alone.
        assert await runner_b.resume_incomplete() == []
        assert await status_of(session_factory, app_id) == ("awaiting_approval", None)

        await runner_b.resume(app_id, ReviewDecision(action="approve"))
        await runner_b.wait(app_id)
        final = await runner_b.snapshot(app_id)

    assert await status_of(session_factory, app_id) == ("completed", None)
    assert llm_b.calls == []  # nothing re-run in process B
    assert final.values["fit_report"]["overall_score"] == 71


async def test_status_lost_while_paused_is_repaired(
    session_factory: Factory, settings: Settings
) -> None:
    """Row says running (e.g. crash right after a resume flipped it) but the checkpoint
    is still paused at the gate: recovery restores awaiting_approval, runs nothing."""
    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await run_to_gate(runner, session_factory)
    async with session_factory() as session:
        await apps.set_status(session, app_id, "running")

    assert await runner.resume_incomplete() == []
    assert await status_of(session_factory, app_id) == ("awaiting_approval", None)
    assert len(llm.calls) == 2


async def test_resume_without_checkpoint_starts_over(
    session_factory: Factory, settings: Settings
) -> None:
    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await seed_application(session_factory)  # status running, never started

    assert await runner.resume_incomplete() == [app_id]
    await runner.wait(app_id)

    assert await status_of(session_factory, app_id) == ("awaiting_approval", None)
    assert [c.output_model for c in llm.calls] == [JobPostingExtraction, FitAssessment]


async def test_finished_run_with_lost_status_is_repaired(
    session_factory: Factory, settings: Settings
) -> None:
    from langgraph.types import Command

    llm = FakeLLMClient(responses=default_responses())
    runner = make_runner(llm, settings, session_factory)
    app_id = await seed_application(session_factory)
    # Drive the graph to the end without the runner, so the row still says "running".
    config = thread_config(app_id)
    await runner._graph.ainvoke(await runner._initial_input(app_id), config)
    await runner._graph.ainvoke(Command(resume={"action": "reject"}), config)

    assert await runner.resume_incomplete() == []
    assert await status_of(session_factory, app_id) == ("rejected", None)


async def test_resume_ignores_terminal_statuses(
    session_factory: Factory, settings: Settings
) -> None:
    runner = make_runner(FakeLLMClient(responses=default_responses()), settings, session_factory)
    ids = [await seed_application(session_factory) for _ in range(3)]
    async with session_factory() as session:
        for app_id, status in zip(ids, ["completed", "failed", "rejected"], strict=True):
            await apps.set_status(session, app_id, status)

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
