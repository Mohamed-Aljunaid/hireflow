import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import FIT_ANALYSIS, PARSE_JOB, build_graph
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitAssessment, FitReport
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.config import Settings
from app.core.llm import LLMRefusalError
from app.services.pipeline_runner import thread_config
from tests.fakes import FakeLLMClient, default_responses, sample_extraction


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, anthropic_analysis_effort="xhigh")


def initial_state() -> dict:
    return {
        "application_id": "app-1",
        "cv": ParsedCV.from_extraction(sample_extraction()).model_dump(mode="json"),
        "job_text": "Senior Python Engineer posting",
    }


def test_graph_shape(settings: Settings) -> None:
    graph = build_graph(FakeLLMClient(), settings).compile()
    nodes = set(graph.get_graph().nodes)
    assert {PARSE_JOB, FIT_ANALYSIS} <= nodes


async def test_graph_runs_end_to_end(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = build_graph(llm, settings).compile(checkpointer=InMemorySaver())

    final = await graph.ainvoke(initial_state(), thread_config("t1"))

    job = JobPosting.model_validate(final["job"])
    report = FitReport.model_validate(final["fit_report"])
    assert job.title == "Senior Python Engineer"
    assert report.overall_score == 71
    assert [c.output_model for c in llm.calls] == [JobPostingExtraction, FitAssessment]
    assert llm.calls[0].user == "<job_posting>\nSenior Python Engineer posting\n</job_posting>"
    assert llm.calls[1].effort == "xhigh"
    # The fit step saw the job the previous node produced.
    assert "[must-3] (skill) Kubernetes in production" in llm.calls[1].user


async def test_state_is_json_only(settings: Settings) -> None:
    """Checkpointed values must be plain JSON types (no Pydantic instances)."""
    import json

    graph = build_graph(FakeLLMClient(responses=default_responses()), settings).compile(
        checkpointer=InMemorySaver()
    )
    final = await graph.ainvoke(initial_state(), thread_config("t2"))
    json.dumps(final)  # raises if anything non-JSON slipped in


async def test_checkpoint_after_each_step(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = build_graph(llm, settings).compile(checkpointer=InMemorySaver())
    config = thread_config("t3")
    await graph.ainvoke(initial_state(), config)

    history = [s async for s in graph.aget_state_history(config)]
    # newest first: END, after fit, after parse_job, input
    nexts = [tuple(s.next) for s in history]
    assert (FIT_ANALYSIS,) in nexts and (PARSE_JOB,) in nexts and () in nexts
    after_parse = next(s for s in history if tuple(s.next) == (FIT_ANALYSIS,))
    assert "job" in after_parse.values and "fit_report" not in after_parse.values


async def test_failing_node_keeps_earlier_progress(settings: Settings) -> None:
    responses = default_responses()
    responses[FitAssessment] = LLMRefusalError("declined")
    graph = build_graph(FakeLLMClient(responses=responses), settings).compile(
        checkpointer=InMemorySaver()
    )
    config = thread_config("t4")

    with pytest.raises(LLMRefusalError):
        await graph.ainvoke(initial_state(), config, durability="sync")

    snapshot = await graph.aget_state(config)
    assert "job" in snapshot.values
    assert "fit_report" not in snapshot.values
    assert tuple(snapshot.next) == (FIT_ANALYSIS,)
