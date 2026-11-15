import uuid

import pytest
from httpx import AsyncClient

from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.llm import LLMRefusalError, LLMUnavailableError
from tests.conftest import SAMPLE_JOB_TEXT
from tests.fakes import FakeLLMClient


async def test_create_job_returns_parsed_posting(
    client: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    resp = await client.post("/jobs", json={"text": SAMPLE_JOB_TEXT})

    assert resp.status_code == 201, resp.text
    job = JobPosting.model_validate(resp.json()["parsed"])
    assert job.title == "Senior Python Engineer"
    assert [r.id for r in job.requirements] == ["must-1", "must-2", "must-3", "nice-1"]
    [call] = fake_llm.calls
    assert call.output_model is JobPostingExtraction
    assert "Kubernetes in production" in call.user


async def test_create_job_strips_whitespace(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    await client.post("/jobs", json={"text": f"\n\n  {SAMPLE_JOB_TEXT}  \n"})
    assert fake_llm.calls[0].user == f"<job_posting>\n{SAMPLE_JOB_TEXT.strip()}\n</job_posting>"


async def test_get_job_round_trip(client: AsyncClient) -> None:
    created = (await client.post("/jobs", json={"text": SAMPLE_JOB_TEXT})).json()
    resp = await client.get(f"/jobs/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


async def test_get_missing_job_returns_404(client: AsyncClient) -> None:
    assert (await client.get(f"/jobs/{uuid.uuid4()}")).status_code == 404


@pytest.mark.parametrize("body", [{}, {"text": "too short"}, {"text": 123}])
async def test_invalid_body_returns_422(
    client: AsyncClient, fake_llm: FakeLLMClient, body: dict
) -> None:
    assert (await client.post("/jobs", json=body)).status_code == 422
    assert fake_llm.calls == []


async def test_too_long_posting_returns_413(
    client: AsyncClient, fake_llm: FakeLLMClient, test_settings
) -> None:
    text = "x" * (test_settings.max_job_posting_chars + 1)
    assert (await client.post("/jobs", json={"text": text})).status_code == 413
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(LLMRefusalError("declined"), 502), (LLMUnavailableError("rate limited"), 503)],
)
async def test_llm_errors_map_to_http(
    client: AsyncClient, fake_llm: FakeLLMClient, session, error: Exception, status: int
) -> None:
    from sqlalchemy import func, select

    from app.db.models import Job

    fake_llm.responses[JobPostingExtraction] = error
    resp = await client.post("/jobs", json={"text": SAMPLE_JOB_TEXT})

    assert resp.status_code == status
    assert (await session.scalar(select(func.count()).select_from(Job))) == 0
