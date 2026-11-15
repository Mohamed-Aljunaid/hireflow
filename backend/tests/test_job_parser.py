import pytest

from app.agents.job_parser import parse_job_posting
from app.agents.prompts import JOB_PARSER_SYSTEM
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.llm import LLMTruncatedError
from tests.fakes import FakeLLMClient, sample_job_extraction


async def test_parse_job_posting_uses_structured_output(fake_llm: FakeLLMClient) -> None:
    job = await parse_job_posting("Senior Python Engineer ...", fake_llm)

    assert isinstance(job, JobPosting)
    [call] = fake_llm.calls
    assert call.output_model is JobPostingExtraction
    assert call.system == JOB_PARSER_SYSTEM
    assert call.user == "<job_posting>\nSenior Python Engineer ...\n</job_posting>"


async def test_parse_job_posting_propagates_llm_errors() -> None:
    llm = FakeLLMClient(responses={JobPostingExtraction: LLMTruncatedError("cut")})
    with pytest.raises(LLMTruncatedError):
        await parse_job_posting("text", llm)


def test_from_extraction_assigns_requirement_ids() -> None:
    job = JobPosting.from_extraction(sample_job_extraction())

    assert [r.id for r in job.must_haves] == ["must-1", "must-2", "must-3"]
    assert [r.id for r in job.nice_to_haves] == ["nice-1"]
    assert {r.importance for r in job.must_haves} == {"must"}
    assert job.nice_to_haves[0].importance == "nice"
    assert [r.id for r in job.requirements] == ["must-1", "must-2", "must-3", "nice-1"]
    assert job.must_haves[0].text == "5+ years of Python backend experience"
    assert job.keywords == sample_job_extraction().keywords


def test_render_with_ids_lists_every_requirement() -> None:
    job = JobPosting.from_extraction(sample_job_extraction())
    rendered = job.render_with_ids()

    assert rendered.startswith("Role: Senior Python Engineer at Northwind Labs")
    for req in job.requirements:
        assert f"[{req.id}] ({req.category}) {req.text}" in rendered
    assert rendered.index("MUST-HAVE") < rendered.index("NICE-TO-HAVE")


def test_job_with_no_requirements() -> None:
    job = JobPosting.from_extraction(JobPostingExtraction(title="Engineer"))
    assert job.requirements == []
    assert "REQUIREMENTS" not in job.render_with_ids()


def test_job_posting_round_trips_through_json() -> None:
    job = JobPosting.from_extraction(sample_job_extraction())
    assert JobPosting.model_validate(job.model_dump(mode="json")) == job
