"""Job posting models.

As with CVs: `JobPostingExtraction` is the LLM output; `JobPosting` adds code-assigned
requirement IDs (`must-1`, `nice-1`) that the Fit Analyst must reference.
"""

from typing import Literal

from pydantic import BaseModel, Field

Seniority = Literal[
    "intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager",
    "director", "executive", "unspecified",
]  # fmt: skip
RemotePolicy = Literal["onsite", "hybrid", "remote", "unspecified"]
RequirementCategory = Literal[
    "skill", "experience", "education", "certification", "language", "other"
]  # fmt: skip


class RequirementExtraction(BaseModel):
    text: str = Field(description="One requirement, close to the posting's wording.")
    category: RequirementCategory


class JobPostingExtraction(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    remote_policy: RemotePolicy = "unspecified"
    employment_type: str | None = Field(None, description="e.g. full-time, contract.")
    seniority: Seniority = "unspecified"
    salary_range: str | None = Field(None, description="As written, if stated.")
    must_haves: list[RequirementExtraction] = Field(
        default_factory=list, description="Required qualifications ('must', 'required')."
    )
    nice_to_haves: list[RequirementExtraction] = Field(
        default_factory=list, description="Preferred/bonus qualifications."
    )
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(
        default_factory=list, description="Technologies, tools and domain terms (ATS keywords)."
    )


class Requirement(BaseModel):
    id: str
    text: str
    category: RequirementCategory
    importance: Literal["must", "nice"]


class JobPosting(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    remote_policy: RemotePolicy = "unspecified"
    employment_type: str | None = None
    seniority: Seniority = "unspecified"
    salary_range: str | None = None
    must_haves: list[Requirement] = Field(default_factory=list)
    nice_to_haves: list[Requirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @classmethod
    def from_extraction(cls, extraction: JobPostingExtraction) -> "JobPosting":
        def reqs(items: list[RequirementExtraction], kind: Literal["must", "nice"]):
            return [
                Requirement(id=f"{kind}-{i}", importance=kind, **r.model_dump())
                for i, r in enumerate(items, 1)
            ]

        return cls(
            **extraction.model_dump(exclude={"must_haves", "nice_to_haves"}),
            must_haves=reqs(extraction.must_haves, "must"),
            nice_to_haves=reqs(extraction.nice_to_haves, "nice"),
        )

    @property
    def requirements(self) -> list[Requirement]:
        return [*self.must_haves, *self.nice_to_haves]

    def render_with_ids(self) -> str:
        head = self.title + (f" at {self.company}" if self.company else "")
        lines = [f"Role: {head}", f"Seniority: {self.seniority}"]
        if self.responsibilities:
            lines += ["", "RESPONSIBILITIES", *(f"- {r}" for r in self.responsibilities)]
        if self.must_haves:
            lines += ["", "MUST-HAVE REQUIREMENTS"]
            lines += [f"[{r.id}] ({r.category}) {r.text}" for r in self.must_haves]
        if self.nice_to_haves:
            lines += ["", "NICE-TO-HAVE REQUIREMENTS"]
            lines += [f"[{r.id}] ({r.category}) {r.text}" for r in self.nice_to_haves]
        return "\n".join(lines)
