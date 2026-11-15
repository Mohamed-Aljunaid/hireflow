"""Fit analysis models.

The LLM returns `FitAssessment`, one verdict per requirement with cited CV IDs. Code then
builds a `FitReport`: it validates every citation against the CV, downgrades claims left
with no evidence, and computes the score deterministically.
"""

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["met", "partial", "not_met"]


# ---------- LLM output ----------


class RequirementJudgement(BaseModel):
    requirement_id: str = Field(description="The [must-N]/[nice-N] ID from the job posting.")
    verdict: Verdict
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="CV item IDs (e.g. exp-1.b2, skill-3) that support the verdict.",
    )
    rationale: str = Field(description="One or two sentences, grounded in the cited items.")


class StrengthClaim(BaseModel):
    text: str
    evidence_refs: list[str] = Field(default_factory=list)


class GapClaim(BaseModel):
    text: str
    requirement_ids: list[str] = Field(default_factory=list)


class FitAssessment(BaseModel):
    judgements: list[RequirementJudgement]
    strengths: list[StrengthClaim] = Field(default_factory=list)
    gaps: list[GapClaim] = Field(default_factory=list)
    summary: str


# ---------- Validated report ----------


class RequirementMatch(BaseModel):
    requirement_id: str
    requirement_text: str
    importance: Literal["must", "nice"]
    verdict: Verdict
    evidence_refs: list[str]
    rationale: str


class FitReport(BaseModel):
    overall_score: int | None = Field(
        description="0-100 from verdicts (must-haves weigh 2x). None if the job lists no "
        "requirements."
    )
    must_have_score: int | None
    nice_to_have_score: int | None
    matches: list[RequirementMatch]
    strengths: list[StrengthClaim]
    gaps: list[GapClaim]
    summary: str
    warnings: list[str] = Field(
        default_factory=list, description="Corrections applied to the model's assessment."
    )
