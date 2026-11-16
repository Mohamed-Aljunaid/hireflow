"""Researcher: job posting (+ optional search results) -> CompanyBrief with sourced facts."""

import logging
from typing import Protocol

from app.agents.prompts import RESEARCHER_SYSTEM
from app.agents.schemas.job import JobPosting
from app.agents.schemas.research import (
    JOB_POSTING_SOURCE,
    CompanyBrief,
    CompanyFact,
    CompanyResearch,
    SearchResult,
    Source,
)
from app.core.llm import LLMClient

logger = logging.getLogger(__name__)


class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]: ...


class NoSearchProvider:
    """Default: no web search, so the brief is built from the job posting alone.

    shortcut: no real search backend yet; add a provider class (e.g. a search API
    client) when company research beyond the posting is needed.
    """

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        return []


async def research_company(
    job: JobPosting, job_text: str, llm: LLMClient, search: SearchProvider
) -> CompanyBrief:
    sources = [Source(id=JOB_POSTING_SOURCE, title="Job posting")]
    blocks = [f"[{JOB_POSTING_SOURCE}] Job posting\n{job_text}"]
    warnings: list[str] = []

    if job.company:
        try:
            results = await search.search(f"{job.company} company", limit=5)
        except Exception as exc:  # research is best-effort; the posting is still usable
            logger.warning("company search failed: %s", exc)
            warnings.append(f"Web search failed ({type(exc).__name__}); used the posting only.")
            results = []
        for i, r in enumerate(results, 1):
            sources.append(Source(id=f"src-{i}", title=r.title, url=r.url))
            blocks.append(f"[src-{i}] {r.title} ({r.url})\n{r.snippet}")

    research = await llm.structured(
        system=RESEARCHER_SYSTEM,
        user=f"Company: {job.company or 'unknown'}\n\n<sources>\n"
        + "\n\n".join(blocks)
        + "\n</sources>",
        output_model=CompanyResearch,
    )

    valid = {s.id for s in sources}
    facts: list[CompanyFact] = []
    for f in research.facts:
        if f.source_id not in valid:
            warnings.append(f"Dropped fact citing unknown source '{f.source_id}': {f.text!r}.")
            continue
        facts.append(CompanyFact(id=f"co-{len(facts) + 1}", **f.model_dump()))

    return CompanyBrief(
        company=job.company,
        summary=research.summary,
        facts=facts,
        sources=sources,
        warnings=warnings,
    )
