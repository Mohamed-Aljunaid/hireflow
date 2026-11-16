import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.graph import (
    CHECK_BULLETS,
    CHECK_LETTER,
    CONTENT_REVIEW,
    FIT_ANALYSIS,
    FIT_REVIEW,
    PARSE_JOB,
    RESEARCH,
    TAILOR_BULLETS,
    WRITE_LETTER,
    build_graph,
)
from app.agents.schemas.content import (
    BulletDraft,
    ClaimCheck,
    CoverLetterDraft,
    ParagraphDraft,
    TailoringDraft,
)
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitAssessment, FitReport
from app.agents.schemas.job import JobPostingExtraction
from app.agents.schemas.research import CompanyResearch
from app.core.config import Settings
from app.core.llm import LLMRefusalError
from app.services.pipeline_runner import pending_review, status_from_snapshot, thread_config
from tests.fakes import (
    FakeLLMClient,
    default_responses,
    flag_units,
    sample_cover_letter_draft,
    sample_extraction,
    sample_tailoring_draft,
)

APPROVE = {"action": "approve"}
PIPELINE_CALLS = [JobPostingExtraction, CompanyResearch, FitAssessment]
DRAFTING_CALLS = [TailoringDraft, ClaimCheck, CoverLetterDraft, ClaimCheck]


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


async def to_content_review(graph, config) -> None:
    await graph.ainvoke(initial_state(), config)
    await graph.ainvoke(Command(resume=APPROVE), config)
    review = pending_review(await graph.aget_state(config))
    assert review is not None and review.gate == CONTENT_REVIEW


def test_graph_shape(settings: Settings) -> None:
    graph = build_graph(FakeLLMClient(), settings).compile()
    assert {
        PARSE_JOB, RESEARCH, FIT_ANALYSIS, FIT_REVIEW, TAILOR_BULLETS, CHECK_BULLETS,
        WRITE_LETTER, CHECK_LETTER, CONTENT_REVIEW,
    } <= set(graph.get_graph().nodes)  # fmt: skip


# ---------- fit gate ----------


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
    assert FitReport.model_validate(review.payload["fit_report"]).overall_score == 71
    assert [c.output_model for c in llm.calls] == PIPELINE_CALLS
    assert llm.calls_for(FitAssessment)[0].effort == "xhigh"
    assert snapshot.values["company_brief"]["facts"][0]["id"] == "co-1"


async def test_fit_edit_feeds_drafting(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
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
    await graph.ainvoke(Command(resume=decision), config)

    report = FitReport.model_validate((await graph.aget_state(config)).values["fit_report"])
    k8s = report.matches[2]
    assert (k8s.verdict, k8s.evidence_refs, k8s.source) == ("partial", ["skill-5"], "human")
    assert report.overall_score == 86  # (2+2+1+1)/7
    # The tailor saw the edited verdict.
    assert "[must-3] partial: Kubernetes in production" in llm.calls_for(TailoringDraft)[0].user


async def test_fit_reject_stops_before_drafting(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t4")
    await graph.ainvoke(initial_state(), config)

    final = await graph.ainvoke(
        Command(resume={"action": "reject", "feedback": "Kubernetes is a hard requirement."}),
        config,
    )

    assert final["rejection"]["gate"] == FIT_REVIEW
    assert status_from_snapshot(await graph.aget_state(config)) == "rejected"
    assert [c.output_model for c in llm.calls] == PIPELINE_CALLS


async def test_continuing_without_answer_stays_paused(settings: Settings) -> None:
    """ainvoke(None) on a paused run (what crash recovery does) just pauses again."""
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t5")
    await graph.ainvoke(initial_state(), config)

    await graph.ainvoke(None, config)

    assert status_from_snapshot(await graph.aget_state(config)) == "awaiting_approval"
    assert len(llm.calls) == len(PIPELINE_CALLS)


# ---------- drafting + claim checks (Phase 5) ----------


async def test_clean_drafts_reach_content_review(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t6")

    await to_content_review(graph, config)

    snapshot = await graph.aget_state(config)
    review = pending_review(snapshot)
    assert review.allowed_actions == ["approve", "edit", "regenerate", "reject"]
    assert [b["id"] for b in review.payload["tailored"]["bullets"]] == [
        "tb-1", "tb-2", "tb-3", "tb-4"
    ]  # fmt: skip
    assert [p["id"] for p in review.payload["cover_letter"]["paragraphs"]] == ["p-1", "p-2", "p-3"]
    assert review.payload["tailored"]["warnings"] == []
    assert [c.output_model for c in llm.calls] == PIPELINE_CALLS + DRAFTING_CALLS
    # The writer saw the brief with fact IDs, and the checker saw the cited fact text.
    assert "[co-1] (culture) The role is remote within the US." in (
        llm.calls_for(CoverLetterDraft)[0].user
    )
    letter_check = llm.calls_for(ClaimCheck)[1].user
    assert "[p-3] I am glad the role is remote" in letter_check
    assert "[co-1] The role is remote within the US." in letter_check


async def test_fabricated_bullet_caught_by_llm_check_and_rewritten(settings: Settings) -> None:
    """Done-when: a fabricated claim is caught and rewritten."""
    fabricated = sample_tailoring_draft()
    fabricated.bullets[0] = BulletDraft(
        text="Led migration to FastAPI microservices on Kubernetes.",  # no Kubernetes on CV
        source_cv_refs=["exp-1.b1"],
    )
    responses = default_responses()
    responses[TailoringDraft] = [fabricated, sample_tailoring_draft()]
    responses[ClaimCheck] = [
        flag_units({"tb-1": "Kubernetes is not in exp-1.b1"}),
        flag_units({}),  # second bullet draft: clean
        flag_units({}),  # letter
    ]
    llm = FakeLLMClient(responses=responses)
    graph = compiled(llm, settings)
    config = thread_config("t7")

    await to_content_review(graph, config)

    values = (await graph.aget_state(config)).values
    texts = [b["text"] for b in values["tailored"]["bullets"]]
    assert not any("Kubernetes" in t for t in texts)
    assert values["tailored"]["warnings"] == []
    assert values["bullet_attempts"] == 2
    rewrite_prompt = llm.calls_for(TailoringDraft)[1].user
    assert "<claim_check_failures>" in rewrite_prompt
    assert '[tb-1] "Led migration to FastAPI microservices on Kubernetes."' in rewrite_prompt
    assert "Kubernetes is not in exp-1.b1" in rewrite_prompt


async def test_invented_number_caught_without_llm_verdict(settings: Settings) -> None:
    """The deterministic layer catches a number the CV never states, even when the
    LLM checker (wrongly) says everything is supported."""
    inflated = sample_tailoring_draft()
    inflated.bullets[1] = BulletDraft(
        text="Cut p95 latency 90% by introducing Redis caching.", source_cv_refs=["exp-1.b2"]
    )
    responses = default_responses()
    responses[TailoringDraft] = [inflated, sample_tailoring_draft()]
    llm = FakeLLMClient(responses=responses)  # ClaimCheck: all_supported
    graph = compiled(llm, settings)
    config = thread_config("t8")

    await to_content_review(graph, config)

    values = (await graph.aget_state(config)).values
    assert "Cut p95 latency 40% by introducing Redis caching." in [
        b["text"] for b in values["tailored"]["bullets"]
    ]
    assert "numbers not in the cited sources: ['90']" in llm.calls_for(TailoringDraft)[1].user


async def test_persistent_fabrication_is_dropped_after_max_rewrites(settings: Settings) -> None:
    """Done-when: if rewrites keep failing, the claim is removed before the human sees it."""
    fabricated = sample_tailoring_draft()
    fabricated.bullets.append(
        BulletDraft(text="Managed a team of engineers.", source_cv_refs=["exp-1"])
    )
    responses = default_responses()
    responses[TailoringDraft] = [fabricated]  # same draft every time
    responses[ClaimCheck] = [
        flag_units({"tb-5": "No people management in exp-1"}),
        flag_units({"tb-5": "No people management in exp-1"}),
        flag_units({"tb-5": "No people management in exp-1"}),
        flag_units({}),  # letter
    ]
    llm = FakeLLMClient(responses=responses)
    graph = compiled(llm, Settings(_env_file=None, claim_check_max_rewrites=2))
    config = thread_config("t9")

    await to_content_review(graph, config)

    values = (await graph.aget_state(config)).values
    assert len(llm.calls_for(TailoringDraft)) == 3  # first draft + 2 rewrites
    assert [b["id"] for b in values["tailored"]["bullets"]] == ["tb-1", "tb-2", "tb-3", "tb-4"]
    [warning] = values["tailored"]["warnings"]
    assert "Removed bullet tb-5" in warning and "No people management" in warning


async def test_fabricated_company_claim_in_letter_is_rewritten(settings: Settings) -> None:
    bad_letter = sample_cover_letter_draft()
    bad_letter.paragraphs[2] = ParagraphDraft(
        text="I admire Northwind's Series C funding.", company_fact_refs=["co-9"]
    )
    responses = default_responses()
    responses[CoverLetterDraft] = [bad_letter, sample_cover_letter_draft()]
    llm = FakeLLMClient(responses=responses)
    graph = compiled(llm, settings)
    config = thread_config("t10")

    await to_content_review(graph, config)

    letter = (await graph.aget_state(config)).values["cover_letter"]
    assert "Series C" not in json.dumps(letter)
    assert "cites unknown company facts ['co-9']" in llm.calls_for(CoverLetterDraft)[1].user


async def test_letter_paragraph_dropped_after_max_rewrites(settings: Settings) -> None:
    responses = default_responses()
    responses[ClaimCheck] = [
        flag_units({}),  # bullets fine
        flag_units({"p-2": "Brightside Health is not cited correctly"}),
    ]
    llm = FakeLLMClient(responses=responses)
    graph = compiled(llm, Settings(_env_file=None, claim_check_max_rewrites=1))
    config = thread_config("t11")

    await to_content_review(graph, config)

    letter = (await graph.aget_state(config)).values["cover_letter"]
    assert [p["id"] for p in letter["paragraphs"]] == ["p-1", "p-3"]
    assert "Removed paragraph p-2" in letter["warnings"][0]
    assert len(llm.calls_for(CoverLetterDraft)) == 2


# ---------- content gate ----------


async def test_content_approve_completes(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t12")
    await to_content_review(graph, config)
    calls = len(llm.calls)

    final = await graph.ainvoke(Command(resume=APPROVE), config)

    assert status_from_snapshot(await graph.aget_state(config)) == "completed"
    assert [r["gate"] for r in final["reviews"]] == [FIT_REVIEW, CONTENT_REVIEW]
    assert len(llm.calls) == calls


async def test_content_edit_replaces_text(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t13")
    await to_content_review(graph, config)

    final = await graph.ainvoke(
        Command(
            resume={
                "action": "edit",
                "text_edits": [
                    {"id": "tb-2", "text": "Reduced p95 latency by 40% with Redis caching."},
                    {"id": "p-3", "text": "I would welcome a conversation."},
                ],
            }
        ),
        config,
    )

    tb2 = final["tailored"]["bullets"][1]
    assert (tb2["text"], tb2["author"], tb2["source_cv_refs"]) == (
        "Reduced p95 latency by 40% with Redis caching.",
        "human",
        ["exp-1.b2"],
    )
    assert final["cover_letter"]["paragraphs"][2]["author"] == "human"
    assert final["reviews"][-1]["edited_items"] == ["tb-2", "p-3"]
    assert status_from_snapshot(await graph.aget_state(config)) == "completed"


async def test_content_regenerate_redrafts_with_feedback(settings: Settings) -> None:
    llm = FakeLLMClient(responses=default_responses())
    graph = compiled(llm, settings)
    config = thread_config("t14")
    await to_content_review(graph, config)

    await graph.ainvoke(
        Command(resume={"action": "regenerate", "feedback": "Lead with the HL7 work."}), config
    )

    snapshot = await graph.aget_state(config)
    assert pending_review(snapshot).gate == CONTENT_REVIEW  # paused again, fresh drafts
    assert len(llm.calls_for(TailoringDraft)) == 2
    assert len(llm.calls_for(CoverLetterDraft)) == 2
    for call in (llm.calls_for(TailoringDraft)[1], llm.calls_for(CoverLetterDraft)[1]):
        assert "<reviewer_feedback>\nLead with the HL7 work.\n</reviewer_feedback>" in call.user
    assert snapshot.values["bullet_attempts"] == 1  # rewrite budget was reset

    await graph.ainvoke(Command(resume=APPROVE), config)
    assert status_from_snapshot(await graph.aget_state(config)) == "completed"


async def test_content_reject(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t15")
    await to_content_review(graph, config)

    final = await graph.ainvoke(Command(resume={"action": "reject"}), config)

    assert final["rejection"]["gate"] == CONTENT_REVIEW
    assert status_from_snapshot(await graph.aget_state(config)) == "rejected"


# ---------- state & checkpoints ----------


async def test_state_is_json_only(settings: Settings) -> None:
    """Checkpointed values must be plain JSON types (no Pydantic instances)."""
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t16")
    await to_content_review(graph, config)
    final = await graph.ainvoke(Command(resume=APPROVE), config)
    json.dumps(final)  # raises if anything non-JSON slipped in


async def test_checkpoint_after_each_step(settings: Settings) -> None:
    graph = compiled(FakeLLMClient(responses=default_responses()), settings)
    config = thread_config("t17")
    await to_content_review(graph, config)

    history = [s async for s in graph.aget_state_history(config)]
    nexts = {tuple(s.next) for s in history}
    for node in (PARSE_JOB, RESEARCH, FIT_ANALYSIS, FIT_REVIEW, TAILOR_BULLETS, CHECK_BULLETS,
                 WRITE_LETTER, CHECK_LETTER, CONTENT_REVIEW):  # fmt: skip
        assert (node,) in nexts


async def test_failing_node_keeps_earlier_progress(settings: Settings) -> None:
    responses = default_responses()
    responses[FitAssessment] = LLMRefusalError("declined")
    graph = compiled(FakeLLMClient(responses=responses), settings)
    config = thread_config("t18")

    with pytest.raises(LLMRefusalError):
        await graph.ainvoke(initial_state(), config, durability="sync")

    snapshot = await graph.aget_state(config)
    assert "job" in snapshot.values and "company_brief" in snapshot.values
    assert "fit_report" not in snapshot.values
    assert tuple(snapshot.next) == (FIT_ANALYSIS,)
