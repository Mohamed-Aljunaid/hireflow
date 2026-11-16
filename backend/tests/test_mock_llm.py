from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.schemas.cv import ParsedCV
from app.api import deps
from app.core.config import Settings
from app.core.llm import AnthropicLLMClient
from app.core.mock_llm import MockLLMClient, sample_extraction
from app.services.pipeline_runner import status_from_snapshot, thread_config


async def test_mock_llm_drives_the_whole_pipeline() -> None:
    graph = build_graph(MockLLMClient(), Settings(_env_file=None)).compile(
        checkpointer=InMemorySaver()
    )
    config = thread_config("demo")
    state = {
        "application_id": "demo",
        "cv": ParsedCV.from_extraction(sample_extraction()).model_dump(mode="json"),
        "job_text": "any text",
    }

    await graph.ainvoke(state, config)
    await graph.ainvoke(Command(resume={"action": "approve"}), config)
    final = await graph.ainvoke(Command(resume={"action": "approve"}), config)

    assert status_from_snapshot(await graph.aget_state(config)) == "completed"
    assert final["fit_report"]["overall_score"] == 71
    assert len(final["tailored"]["bullets"]) == 4
    assert final["tailored"]["warnings"] == final["cover_letter"]["warnings"] == []


def test_llm_mock_setting_selects_mock_client(monkeypatch) -> None:
    deps._default_llm_client.cache_clear()
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None, llm_mock=True))
    try:
        assert isinstance(deps.get_llm_client(), MockLLMClient)
        deps._default_llm_client.cache_clear()
        monkeypatch.setattr(deps, "get_settings", lambda: Settings(_env_file=None))
        assert isinstance(deps.get_llm_client(), AnthropicLLMClient)
    finally:
        deps._default_llm_client.cache_clear()
