import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.graph import FIT_ANALYSIS, FIT_REVIEW, PARSE_JOB, build_graph
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitAssessment, FitReport
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.config import Settings
from app.core.llm import LLMRefusalError
from app.services.pipeline_runner import pending_review, status_from_snapshot, thread_config
from tests.fakes import FakeLLMClient, default_responses, sample_extraction

APPROVE = {"action": "approve"}


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, anthropic_analysis_effort="xhigh")


def initial_state() -> dict:
    return {
        "application_id": "app-1",
        "cv": ParsedCV.from_extraction(sample_extraction()).model_dump(mode="json"),
        "job_text": "Senior Python Engineer posting",
    }


def compiled(llm: FakeLLMClient, settings: Settings):
    return build_graph(llm, settings).compile(checkpointer=InMemorySaver())


def test_graph_shape(settings: Settings) -> None:
    graph = build_graph(FakeLLMClient(), settings).compile()
    assert {PARSE_JOB, FIT_ANALYSIS, FIT_REVIEW} <= set(graph.get_graph().nodes)


async def test_graph_pauses_at_fit_review(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t1")

    await graph.ainvoke(initial_state(), config)
    snapshot = await graph.aget_state(config)

    assert tuple(snapshot.next) == (FIT_REVIEW,)
    assert status_from_snapshot(snapshot) == "awaiting_approval"
    review = pending_review(snapshot)
    assert review is not None
    assert review.gate == FIT_REVIEW
    assert review.allowed_actions == ["approve", "edit", "reject"]
    report = FitReport.model_validate(review.payload["fit_report"])
    assert report.overall_score == 71
    assert [c.output_model for c in llm.calls] == [JobPostingExtraction, FitAssessment]
    assert llm.calls[1].effort == "xhigh"
    assert "[must-3] (skill) Kubernetes in production" in llm.calls[1].user


async def test_approve_completes_without_more_llm_calls(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t2")
    await graph.ainvoke(initial_state(), config)

    final = await graph.ainvoke(Command(resume=APPROVE | {"feedback": "go"}), config)

    snapshot = await graph.aget_state(config)
    assert status_from_snapshot(snapshot) == "completed"
    assert JobPosting.model_validate(final["job"]).title == "Senior Python Engineer"
    assert final["fit_report"]["overall_score"] == 71
    [review] = final["reviews"]
    assert (review["gate"], review["action"], review["feedback"]) == (FIT_REVIEW, "approve", "go")
    assert "rejection" not in final
    assert len(llm.calls) == 2


async def test_edit_applies_override_and_rescores(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t3")
    await graph.ainvoke(initial_state(), config)

    decision = {
        "action": "edit",
        "match_overrides": [
            {
                "requirement_id": "must-3",
                "verdict": "partial",
                "evidence_refs": ["skill-5"],
                "note": "Docker experience transfers partly to Kubernetes.",
            }
        ],
    }
    final = await graph.ainvoke(Command(resume=decision), config)

    report = FitReport.model_validate(final["fit_report"])
    k8s = report.matches[2]
    assert (k8s.verdict, k8s.evidence_refs, k8s.source) == ("partial", ["skill-5"], "human")
    assert k8s.rationale.startswith("[Reviewer] Docker")
    assert report.overall_score == 86  # (2+2+1+1)/7
    assert report.matches[0].source == "analyst"
    assert final["reviews"][0]["overridden_requirements"] == ["must-3"]
    assert status_from_snapshot(await graph.aget_state(config)) == "completed"


async def test_reject_stops_with_rejection(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t4")
    await graph.ainvoke(initial_state(), config)

    final = await graph.ainvoke(
        Command(resume={"action": "reject", "feedback": "Kubernetes is a hard requirement."}),
        config,
    )

    assert final["rejection"]["feedback"] == "Kubernetes is a hard requirement."
    assert final["rejection"]["gate"] == FIT_REVIEW
    assert status_from_snapshot(await graph.aget_state(config)) == "rejected"


async def test_continuing_without_answer_stays_paused(settings: Settings) -> None:
    """ainvoke(None) on a paused run (what crash recovery does) just pauses again."""
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t5")
    await graph.ainvoke(initial_state(), config)

    await graph.ainvoke(None, config)

    snapshot = await graph.aget_state(config)
    assert status_from_snapshot(snapshot) == "awaiting_approval"
    assert len(llm.calls) == 2


async def test_state_is_json_only(settings: Settings) -> None:
    """Checkpointed values must be plain JSON types (no Pydantic instances)."""
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t6")
    await graph.ainvoke(initial_state(), config)
    final = await graph.ainvoke(Command(resume=APPROVE), config)
    json.dumps(final)  # raises if anything non-JSON slipped in


async def test_checkpoint_after_each_step(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t7")
    await graph.ainvoke(initial_state(), config)
    await graph.ainvoke(Command(resume=APPROVE), config)

    history = [s async for s in graph.aget_state_history(config)]
    nexts = {tuple(s.next) for s in history}
    assert {(PARSE_JOB,), (FIT_ANALYSIS,), (FIT_REVIEW,), ()} <= nexts
    after_parse = next(s for s in history if tuple(s.next) == (FIT_ANALYSIS,))
    assert "job" in after_parse.values and "fit_report" not in after_parse.values


async def test_failing_node_keeps_earlier_progress(settings: Settings) -> None:
    responses = default_responses()
    responses[FitAssessment] = LLMRefusalError("declined")
    graph = compiled(FakeLLMClient(responses=responses), settings)
    config = thread_config("t8")

    with pytest.raises(LLMRefusalError):
        await graph.ainvoke(initial_state(), config, durability="sync")

    snapshot = await graph.aget_state(config)
    assert "job" in snapshot.values
    assert "fit_report" not in snapshot.values
    assert tuple(snapshot.next) == (FIT_ANALYSIS,)
