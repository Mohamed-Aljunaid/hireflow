"""Human-in-the-loop review models.

A gate pauses the graph with `interrupt(...)`. The human answers with a
`ReviewDecision`, which the API validates before resuming with `Command(resume=...)`.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.agents.schemas.fit import Verdict

Gate = Literal["fit_review"]  # Phase 5 adds the tailoring and cover-letter gates
Action = Literal["approve", "edit", "reject"]

GATE_ACTIONS: dict[str, tuple[Action, ...]] = {
    "fit_review": ("approve", "edit", "reject"),
}


class MatchOverride(BaseModel):
    """Human correction of one fit verdict. Evidence must still be real CV IDs."""

    requirement_id: str
    verdict: Verdict
    evidence_refs: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1, max_length=1000, description="Why the verdict changed.")


class ReviewDecision(BaseModel):
    action: Action
    feedback: str | None = Field(None, max_length=2000)
    match_overrides: list[MatchOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def _overrides_only_with_edit(self) -> Self:
        if self.action == "edit" and not self.match_overrides:
            raise ValueError("action 'edit' needs at least one match override")
        if self.action != "edit" and self.match_overrides:
            raise ValueError(f"action '{self.action}' cannot carry match overrides")
        ids = [o.requirement_id for o in self.match_overrides]
        if len(ids) != len(set(ids)):
            raise ValueError("each requirement can be overridden at most once")
        return self


class ReviewRecord(BaseModel):
    """What the pipeline remembers about a decision (state['reviews'])."""

    gate: Gate
    action: Action
    feedback: str | None = None
    overridden_requirements: list[str] = Field(default_factory=list)
    decided_at: str


class PendingReview(BaseModel):
    """What GET /applications/{id} shows while the run is paused."""

    gate: Gate
    allowed_actions: list[Action]
    payload: dict = Field(description="The artifact under review, e.g. the fit report.")
