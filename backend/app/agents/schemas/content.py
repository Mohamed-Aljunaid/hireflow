"""Tailored bullets, cover letter and claim-check models.

Drafts are LLM output; code assigns IDs (tb-N, p-N). Every claim cites its sources:
CV item IDs (`source_cv_refs`) and, for the letter, company fact IDs (`company_fact_refs`).
"""

from typing import Literal

from pydantic import BaseModel, Field

Author = Literal["model", "human"]


# ---------- LLM output ----------


class BulletDraft(BaseModel):
    text: str = Field(description="One CV bullet, rephrased for this job.")
    source_cv_refs: list[str] = Field(description="CV item IDs this bullet is based on.")
    requirement_ids: list[str] = Field(
        default_factory=list, description="Job requirement IDs this bullet speaks to."
    )


class TailoringDraft(BaseModel):
    bullets: list[BulletDraft]


class ParagraphDraft(BaseModel):
    text: str
    source_cv_refs: list[str] = Field(default_factory=list)
    company_fact_refs: list[str] = Field(default_factory=list)


class CoverLetterDraft(BaseModel):
    salutation: str
    paragraphs: list[ParagraphDraft]
    closing: str


class ClaimFinding(BaseModel):
    unit_id: str = Field(description="The [tb-N] or [p-N] ID being judged.")
    supported: bool
    problems: list[str] = Field(
        default_factory=list, description="Each statement not supported by the cited sources."
    )


class ClaimCheck(BaseModel):
    findings: list[ClaimFinding]


# ---------- Validated artifacts (stored in graph state) ----------


class TailoredBullet(BaseModel):
    id: str
    text: str
    source_cv_refs: list[str]
    requirement_ids: list[str] = Field(default_factory=list)
    author: Author = "model"


class TailoredBullets(BaseModel):
    bullets: list[TailoredBullet]
    warnings: list[str] = Field(default_factory=list)


class CoverLetterParagraph(BaseModel):
    id: str
    text: str
    source_cv_refs: list[str] = Field(default_factory=list)
    company_fact_refs: list[str] = Field(default_factory=list)
    author: Author = "model"


class CoverLetter(BaseModel):
    salutation: str
    paragraphs: list[CoverLetterParagraph]
    closing: str
    warnings: list[str] = Field(default_factory=list)

    def render(self) -> str:
        return "\n\n".join([self.salutation, *(p.text for p in self.paragraphs), self.closing])
