"""LangGraph pipeline state.

Values are JSON-compatible dicts (Pydantic `model_dump(mode="json")`), not model
instances. The checkpointer serialises state on every step; plain JSON avoids the
serializer's class allowlist, survives model refactors, and is readable in Postgres.
Nodes validate their inputs with the Pydantic models at the boundary.
"""

import operator
from typing import Annotated, Any, TypedDict


class PipelineState(TypedDict, total=False):
    application_id: str
    cv: dict[str, Any]  # ParsedCV
    job_text: str
    job: dict[str, Any]  # JobPosting
    fit_report: dict[str, Any]  # FitReport
    company_brief: dict[str, Any]  # CompanyBrief
    tailored: dict[str, Any]  # TailoredBullets
    cover_letter: dict[str, Any]  # CoverLetter
    # Claim-check rewrite loops: drafts so far, and the failures to fix in the next one.
    bullet_attempts: int
    bullet_feedback: list[str]
    letter_attempts: int
    letter_feedback: list[str]
    # Set by a "regenerate" decision; read by every later draft.
    reviewer_feedback: str | None
    # Human-in-the-loop: every decision, appended (ReviewRecord dicts).
    reviews: Annotated[list[dict[str, Any]], operator.add]
    # Set when a reviewer rejects; the graph routes to END.
    rejection: dict[str, Any]  # ReviewRecord
