"""The HireFlow pipeline graph.

Phase 3: parse_job -> fit_analysis -> END. Later phases add research, human approval,
tailoring, claim checking and writing.
"""

from langgraph.graph import END, START, StateGraph

from app.agents.fit_analyst import analyse_fit
from app.agents.job_parser import parse_job_posting
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.job import JobPosting
from app.agents.state import PipelineState
from app.core.config import Settings
from app.core.llm import LLMClient

PARSE_JOB = "parse_job"
FIT_ANALYSIS = "fit_analysis"


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

    graph = StateGraph(PipelineState)
    graph.add_node(PARSE_JOB, parse_job)
    graph.add_node(FIT_ANALYSIS, fit_analysis)
    graph.add_edge(START, PARSE_JOB)
    graph.add_edge(PARSE_JOB, FIT_ANALYSIS)
    graph.add_edge(FIT_ANALYSIS, END)
    return graph
