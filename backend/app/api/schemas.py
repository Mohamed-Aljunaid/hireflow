import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.agents.schemas.content import CoverLetter, TailoredBullets
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.agents.schemas.research import CompanyBrief
from app.agents.schemas.review import PendingReview, ReviewRecord
from app.services.job_search import WebUrl


class CVRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    created_at: datetime
    parsed: ParsedCV

    @computed_field
    @property
    def evidence(self) -> dict[str, str]:
        """Every citable CV item by ID (what bullets, fit matches and edits reference)."""
        return self.parsed.evidence_index()


class JobCreate(BaseModel):
    # Upper bound is enforced against settings in the route.
    text: str = Field(min_length=50, description="The job posting, pasted as plain text.")


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    parsed: JobPosting


class ApplicationCreate(BaseModel):
    cv_id: uuid.UUID
    apply_url: WebUrl | None = None
    job_text: str = Field(min_length=50, description="The job posting, pasted as plain text.")


class ApplicationRead(BaseModel):
    id: uuid.UUID
    cv_id: uuid.UUID
    status: str
    error: str | None
    apply_url: str | None = None
    created_at: datetime
    updated_at: datetime
    next_steps: list[str] = Field(description="Graph nodes still to run (empty when done).")
    pending_review: PendingReview | None = Field(
        None, description="Set while status is awaiting_approval: what to review, and how."
    )
    reviews: list[ReviewRecord] = Field(default_factory=list)
    job: JobPosting | None = None
    fit_report: FitReport | None = None
    company_brief: CompanyBrief | None = None
    tailored: TailoredBullets | None = None
    cover_letter: CoverLetter | None = None


class FitRequest(BaseModel):
    cv_id: uuid.UUID
    job_id: uuid.UUID


class FitResponse(BaseModel):
    cv_id: uuid.UUID
    job_id: uuid.UUID
    report: FitReport
