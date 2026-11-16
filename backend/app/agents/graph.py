r"""The HireFlow pipeline graph.

parse_job -> research -> fit_analysis -> [fit_review] -> tailor_bullets -> check_bullets
    -> write_letter -> check_letter -> [content_review] -> END

- check_bullets / check_letter loop back to their drafting node with the failures, at most
  `claim_check_max_rewrites` times; after that, unsupported items are dropped.
- [gates] pause for a human. reject -> END ("rejected"); content_review "regenerate"
  -> tailor_bullets with the reviewer's feedback.
"""

from datetime import UTC, datetime
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.claim_checker import (
    bullet_units,
    check_claims,
    drop_bullets,
    drop_paragraphs,
    feedback_lines,
    paragraph_units,
)
from app.agents.drafting import tailor_bullets, write_cover_letter
from app.agents.fit_analyst import analyse_fit
from app.agents.job_parser import parse_job_posting
from app.agents.researcher import NoSearchProvider, SearchProvider, research_company
from app.agents.review import apply_fit_overrides, apply_text_edits, validate_decision
from app.agents.schemas.content import CoverLetter, TailoredBullets
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.agents.schemas.research import CompanyBrief
from app.agents.schemas.review import GATE_ACTIONS, ReviewDecision, ReviewRecord
from app.agents.state import PipelineState
from app.core.config import Settings
from app.core.llm import LLMClient

PARSE_JOB = "parse_job"
RESEARCH = "research"
FIT_ANALYSIS = "fit_analysis"
FIT_REVIEW = "fit_review"
TAILOR_BULLETS = "tailor_bullets"
CHECK_BULLETS = "check_bullets"
WRITE_LETTER = "write_letter"
CHECK_LETTER = "check_letter"
CONTENT_REVIEW = "content_review"

GATES = {FIT_REVIEW, CONTENT_REVIEW}


def _record(gate: str, decision: ReviewDecision) -> dict:
    return ReviewRecord(
        gate=gate,
        action=decision.action,
        feedback=decision.feedback,
        overridden_requirements=[o.requirement_id for o in decision.match_overrides],
        edited_items=[e.id for e in decision.text_edits],
        decided_at=datetime.now(UTC).isoformat(),
    ).model_dump(mode="json")


def _ask(gate: str, payload: dict, state: PipelineState) -> ReviewDecision:
    """Pause for a human. Code before interrupt() re-runs on resume: keep it pure."""
    raw = interrupt({"gate": gate, "allowed_actions": list(GATE_ACTIONS[gate]), "payload": payload})
    decision = ReviewDecision.model_validate(raw)
    validate_decision(gate, decision, state)  # the API already checked; defensive
    return decision


def build_graph(
    llm: LLMClient, settings: Settings, search: SearchProvider | None = None
) -> StateGraph:
    """Return the uncompiled graph; callers compile it with their checkpointer."""
    search = search or NoSearchProvider()
    effort = settings.anthropic_analysis_effort
    max_rewrites = settings.claim_check_max_rewrites

    def cv(state: PipelineState) -> ParsedCV:
        return ParsedCV.model_validate(state["cv"])

    def job(state: PipelineState) -> JobPosting:
        return JobPosting.model_validate(state["job"])

    def fit(state: PipelineState) -> FitReport:
        return FitReport.model_validate(state["fit_report"])

    async def parse_job(state: PipelineState) -> PipelineState:
        parsed = await parse_job_posting(state["job_text"], llm)
        return {"job": parsed.model_dump(mode="json")}

    async def research(state: PipelineState) -> PipelineState:
        brief = await research_company(job(state), state["job_text"], llm, search)
        return {"company_brief": brief.model_dump(mode="json")}

    async def fit_analysis(state: PipelineState) -> PipelineState:
        report = await analyse_fit(cv(state), job(state), llm, effort=effort)
        return {"fit_report": report.model_dump(mode="json")}

    async def fit_review(state: PipelineState) -> PipelineState:
        decision = _ask(FIT_REVIEW, {"fit_report": state["fit_report"]}, state)
        record = _record(FIT_REVIEW, decision)
        if decision.action == "reject":
            return {"reviews": [record], "rejection": record}
        update: PipelineState = {"reviews": [record]}
        if decision.action == "edit":
            report = apply_fit_overrides(fit(state), cv(state), decision.match_overrides)
            update["fit_report"] = report.model_dump(mode="json")
        return update

    async def tailor(state: PipelineState) -> PipelineState:
        tailored = await tailor_bullets(
            cv(state),
            job(state),
            fit(state),
            llm,
            check_feedback=state.get("bullet_feedback", []),
            reviewer_feedback=state.get("reviewer_feedback"),
            effort=effort,
        )
        return {
            "tailored": tailored.model_dump(mode="json"),
            "bullet_attempts": state.get("bullet_attempts", 0) + 1,
        }

    async def check_bullets(state: PipelineState) -> PipelineState:
        tailored = TailoredBullets.model_validate(state["tailored"])
        units = bullet_units(tailored)
        problems = await check_claims(units, cv(state), None, llm, effort=effort)
        if not problems:
            return {"bullet_feedback": []}
        if state["bullet_attempts"] <= max_rewrites:
            return {"bullet_feedback": feedback_lines(units, problems)}
        return {
            "tailored": drop_bullets(tailored, problems).model_dump(mode="json"),
            "bullet_feedback": [],
        }

    async def write(state: PipelineState) -> PipelineState:
        letter = await write_cover_letter(
            cv(state),
            job(state),
            fit(state),
            TailoredBullets.model_validate(state["tailored"]),
            CompanyBrief.model_validate(state["company_brief"]),
            llm,
            check_feedback=state.get("letter_feedback", []),
            reviewer_feedback=state.get("reviewer_feedback"),
            effort=effort,
        )
        return {
            "cover_letter": letter.model_dump(mode="json"),
            "letter_attempts": state.get("letter_attempts", 0) + 1,
        }

    async def check_letter(state: PipelineState) -> PipelineState:
        letter = CoverLetter.model_validate(state["cover_letter"])
        units = paragraph_units(letter)
        brief = CompanyBrief.model_validate(state["company_brief"])
        problems = await check_claims(units, cv(state), brief, llm, effort=effort)
        if not problems:
            return {"letter_feedback": []}
        if state["letter_attempts"] <= max_rewrites:
            return {"letter_feedback": feedback_lines(units, problems)}
        return {
            "cover_letter": drop_paragraphs(letter, problems).model_dump(mode="json"),
            "letter_feedback": [],
        }

    async def content_review(state: PipelineState) -> PipelineState:
        payload = {
            "tailored": state["tailored"],
            "cover_letter": state["cover_letter"],
            "company_brief": state["company_brief"],
        }
        decision = _ask(CONTENT_REVIEW, payload, state)
        record = _record(CONTENT_REVIEW, decision)
        if decision.action == "reject":
            return {"reviews": [record], "rejection": record}
        if decision.action == "regenerate":
            # Fresh drafting round: new rewrite budgets, reviewer feedback in every prompt.
            return {
                "reviews": [record],
                "reviewer_feedback": decision.feedback,
                "bullet_attempts": 0,
                "bullet_feedback": [],
                "letter_attempts": 0,
                "letter_feedback": [],
            }
        update: PipelineState = {"reviews": [record]}
        if decision.action == "edit":
            tailored, letter = apply_text_edits(
                TailoredBullets.model_validate(state["tailored"]),
                CoverLetter.model_validate(state["cover_letter"]),
                decision.text_edits,
            )
            update["tailored"] = tailored.model_dump(mode="json")
            update["cover_letter"] = letter.model_dump(mode="json")
        return update

    def after_fit_review(state: PipelineState) -> Literal["rejected", "approved"]:
        return "rejected" if "rejection" in state else "approved"

    def after_check(feedback_key: str):
        def route(state: PipelineState) -> Literal["rewrite", "next"]:
            return "rewrite" if state.get(feedback_key) else "next"

        return route

    def after_content_review(state: PipelineState) -> Literal["rejected", "regenerate", "done"]:
        if "rejection" in state:
            return "rejected"
        return "regenerate" if state["reviews"][-1]["action"] == "regenerate" else "done"

    graph = StateGraph(PipelineState)
    for name, node in [
        (PARSE_JOB, parse_job),
        (RESEARCH, research),
        (FIT_ANALYSIS, fit_analysis),
        (FIT_REVIEW, fit_review),
        (TAILOR_BULLETS, tailor),
        (CHECK_BULLETS, check_bullets),
        (WRITE_LETTER, write),
        (CHECK_LETTER, check_letter),
        (CONTENT_REVIEW, content_review),
    ]:
        graph.add_node(name, node)

    graph.add_edge(START, PARSE_JOB)
    graph.add_edge(PARSE_JOB, RESEARCH)
    graph.add_edge(RESEARCH, FIT_ANALYSIS)
    graph.add_edge(FIT_ANALYSIS, FIT_REVIEW)
    graph.add_conditional_edges(
        FIT_REVIEW, after_fit_review, {"rejected": END, "approved": TAILOR_BULLETS}
    )
    graph.add_edge(TAILOR_BULLETS, CHECK_BULLETS)
    graph.add_conditional_edges(
        CHECK_BULLETS,
        after_check("bullet_feedback"),
        {"rewrite": TAILOR_BULLETS, "next": WRITE_LETTER},
    )
    graph.add_edge(WRITE_LETTER, CHECK_LETTER)
    graph.add_conditional_edges(
        CHECK_LETTER,
        after_check("letter_feedback"),
        {"rewrite": WRITE_LETTER, "next": CONTENT_REVIEW},
    )
    graph.add_conditional_edges(
        CONTENT_REVIEW,
        after_content_review,
        {"rejected": END, "regenerate": TAILOR_BULLETS, "done": END},
    )
    return graph
