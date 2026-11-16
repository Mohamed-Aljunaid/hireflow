"""Company research models. Every fact must cite a source the researcher was given."""

from typing import Literal

from pydantic import BaseModel, Field

FactCategory = Literal["product", "mission", "values", "news", "culture", "other"]

JOB_POSTING_SOURCE = "job_posting"


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class Source(BaseModel):
    id: str  # "job_posting" or "src-N"
    title: str
    url: str | None = None


# ---------- LLM output ----------


class FactExtraction(BaseModel):
    text: str = Field(description="One fact about the company, stated plainly.")
    category: FactCategory
    source_id: str = Field(description="ID of the source that states this fact.")


class CompanyResearch(BaseModel):
    summary: str = Field(description="2-3 sentences: what the company does, from the sources.")
    facts: list[FactExtraction] = Field(default_factory=list)


# ---------- Validated brief ----------


class CompanyFact(BaseModel):
    id: str  # "co-N"
    text: str
    category: FactCategory
    source_id: str


class CompanyBrief(BaseModel):
    company: str | None
    summary: str
    facts: list[CompanyFact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def fact_index(self) -> dict[str, str]:
        return {f.id: f.text for f in self.facts}

    def render_with_ids(self) -> str:
        lines = [f"Company: {self.company or 'unknown'}", f"Summary: {self.summary}"]
        lines += [f"[{f.id}] ({f.category}) {f.text}" for f in self.facts]
        return "\n".join(lines)
