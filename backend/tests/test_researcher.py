import pytest

from app.agents.researcher import NoSearchProvider, research_company
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.agents.schemas.research import CompanyResearch, FactExtraction, SearchResult
from tests.fakes import FakeLLMClient, sample_job_extraction


class FakeSearch:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results, self.error, self.queries = results or [], error, []

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.results


@pytest.fixture
def job() -> JobPosting:
    return JobPosting.from_extraction(sample_job_extraction())


def research(*facts: tuple[str, str]) -> CompanyResearch:
    return CompanyResearch(
        summary="s",
        facts=[FactExtraction(text=t, category="other", source_id=s) for t, s in facts],
    )


async def test_posting_only_by_default(job: JobPosting) -> None:
    llm = FakeLLMClient(responses={CompanyResearch: research(("Remote US", "job_posting"))})

    brief = await research_company(job, "THE POSTING", llm, NoSearchProvider())

    assert [s.id for s in brief.sources] == ["job_posting"]
    assert [(f.id, f.source_id) for f in brief.facts] == [("co-1", "job_posting")]
    assert "[job_posting] Job posting\nTHE POSTING" in llm.calls[0].user
    assert brief.company == "Northwind Labs"


async def test_search_results_become_cited_sources(job: JobPosting) -> None:
    search = FakeSearch(
        [SearchResult(title="About", url="https://nw.example/about", snippet="We build X")]
    )
    llm = FakeLLMClient(
        responses={CompanyResearch: research(("Builds X", "src-1"), ("Remote", "job_posting"))}
    )

    brief = await research_company(job, "posting", llm, search)

    assert search.queries == ["Northwind Labs company"]
    assert [s.id for s in brief.sources] == ["job_posting", "src-1"]
    assert brief.sources[1].url == "https://nw.example/about"
    assert "[src-1] About (https://nw.example/about)\nWe build X" in llm.calls[0].user
    assert [f.id for f in brief.facts] == ["co-1", "co-2"]


async def test_facts_with_unknown_sources_are_dropped(job: JobPosting) -> None:
    llm = FakeLLMClient(
        responses={CompanyResearch: research(("Series C", "src-7"), ("Remote", "job_posting"))}
    )

    brief = await research_company(job, "posting", llm, NoSearchProvider())

    assert [(f.id, f.text) for f in brief.facts] == [("co-1", "Remote")]
    assert "src-7" in brief.warnings[0]


async def test_search_failure_falls_back_to_posting(job: JobPosting) -> None:
    llm = FakeLLMClient(responses={CompanyResearch: research()})

    brief = await research_company(job, "posting", llm, FakeSearch(error=TimeoutError()))

    assert [s.id for s in brief.sources] == ["job_posting"]
    assert "TimeoutError" in brief.warnings[0]


async def test_no_company_name_skips_search() -> None:
    search = FakeSearch()
    job = JobPosting.from_extraction(JobPostingExtraction(title="Engineer"))
    llm = FakeLLMClient(responses={CompanyResearch: research()})

    brief = await research_company(job, "posting", llm, search)

    assert search.queries == []
    assert brief.company is None
