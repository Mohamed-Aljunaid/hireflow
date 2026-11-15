"""LangGraph pipeline state.

Values are JSON-compatible dicts (Pydantic `model_dump(mode="json")`), not model
instances. The checkpointer serialises state on every step; plain JSON avoids the
serializer's class allowlist, survives model refactors, and is readable in Postgres.
Nodes validate their inputs with the Pydantic models at the boundary.
"""

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    application_id: str
    cv: dict[str, Any]  # ParsedCV
    job_text: str
    job: dict[str, Any]  # JobPosting
    fit_report: dict[str, Any]  # FitReport
