r"""The HireFlow pipeline graph.

parse_job -> fit_analysis -> fit_review (human gate) -> END
                                  \-- reject --> END (status "rejected")

Phase 5 inserts research, tailoring, claim checking and writing (with their own gates)
on the "approved" branch.
"""

from datetime import UTC, datetime
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.fit_analyst import analyse_fit
from app.agents.job_parser import parse_job_posting
from app.agents.review import apply_fit_overrides, check_action_allowed
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.agents.schemas.review import GATE_ACTIONS, ReviewDecision, ReviewRecord
from app.agents.state import PipelineState
from app.core.config import Settings
from app.core.llm import LLMClient

PARSE_JOB = "parse_job"
FIT_ANALYSIS = "fit_analysis"
FIT_REVIEW = "fit_review"

GATES = {FIT_REVIEW}


def build_graph(llm: LLMClient, settings: Settings) -> StateGraph:
    """Return the uncompiled graph; callers compile it with their checkpointer."""

    async def parse_job(state: PipelineState) -> PipelineState:
        job = await parse_job_posting(state["job_text"], llm)
        return {"job": job.model_dump(mode="json")}

    async def fit_analysis(state: PipelineState) -> PipelineState:
        report = await analyse_fit(
            ParsedCV.model_validate(state["cv"]),
            JobPosting.model_validate(state["job"]),
            llm,
            effort=settings.anthropic_analysis_effort,
        )
        return {"fit_report": report.model_dump(mode="json")}

    async def fit_review(state: PipelineState) -> PipelineState:
        # Everything before interrupt() re-runs on resume, so it must stay side-effect free.
        raw = interrupt(
            {
                "gate": FIT_REVIEW,
                "allowed_actions": list(GATE_ACTIONS[FIT_REVIEW]),
                "payload": {"fit_report": state["fit_report"]},
            }
        )
        decision = ReviewDecision.model_validate(raw)
        check_action_allowed(FIT_REVIEW, decision)  # the API already checked; defensive
        record = ReviewRecord(
            gate=FIT_REVIEW,
            action=decision.action,
            feedback=decision.feedback,
            overridden_requirements=[o.requirement_id for o in decision.match_overrides],
            decided_at=datetime.now(UTC).isoformat(),
        ).model_dump(mode="json")

        if decision.action == "reject":
            return {"reviews": [record], "rejection": record}
        update: PipelineState = {"reviews": [record]}
        if decision.action == "edit":
            report = apply_fit_overrides(
                FitReport.model_validate(state["fit_report"]),
                ParsedCV.model_validate(state["cv"]),
                decision.match_overrides,
            )
            update["fit_report"] = report.model_dump(mode="json")
        return update

    def after_fit_review(state: PipelineState) -> Literal["rejected", "approved"]:
        return "rejected" if "rejection" in state else "approved"

    graph = StateGraph(PipelineState)
    graph.add_node(PARSE_JOB, parse_job)
    graph.add_node(FIT_ANALYSIS, fit_analysis)
    graph.add_node(FIT_REVIEW, fit_review)
    graph.add_edge(START, PARSE_JOB)
    graph.add_edge(PARSE_JOB, FIT_ANALYSIS)
    graph.add_edge(FIT_ANALYSIS, FIT_REVIEW)
    graph.add_conditional_edges(FIT_REVIEW, after_fit_review, {"rejected": END, "approved": END})
    return graph
