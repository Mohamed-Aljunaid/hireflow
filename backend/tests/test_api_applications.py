import uuid

import pytest
from httpx import AsyncClient

from app.agents.schemas.fit import FitAssessment
from app.core.llm import LLMUnavailableError
from app.services.pipeline_runner import PipelineRunner
from tests.conftest import SAMPLE_CV_TEXT, SAMPLE_JOB_TEXT
from tests.fakes import FakeLLMClient


async def upload_cv(client: AsyncClient) -> str:
    resp = await client.post("/cvs", files={"file": ("cv.txt", SAMPLE_CV_TEXT.encode())})
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_create_runs_pipeline_in_background(
    client: AsyncClient, runner: PipelineRunner, fake_llm: FakeLLMClient
) -> None:
    cv_id = await upload_cv(client)

    resp = await client.post("/applications", json={"cv_id": cv_id, "job_text": SAMPLE_JOB_TEXT})

    assert resp.status_code == 202, resp.text
    created = resp.json()
    assert created["status"] == "running"
    assert created["cv_id"] == cv_id

    await runner.wait(uuid.UUID(created["id"]))
    done = (await client.get(f"/applications/{created['id']}")).json()

    assert done["status"] == "completed"
    assert done["error"] is None
    assert done["next_steps"] == []
    assert done["job"]["title"] == "Senior Python Engineer"
    assert done["fit_report"]["overall_score"] == 71
    assert [m["requirement_id"] for m in done["fit_report"]["matches"]] == [
        "must-1",
        "must-2",
        "must-3",
        "nice-1",
    ]
    # The pipeline parsed the job text sent with the application.
    assert "Kubernetes in production" in fake_llm.calls[1].user


async def test_failed_run_is_reported(
    client: AsyncClient, runner: PipelineRunner, fake_llm: FakeLLMClient
) -> None:
    cv_id = await upload_cv(client)
    fake_llm.responses[FitAssessment] = LLMUnavailableError("Anthropic rate limit reached")

    created = (
        await client.post("/applications", json={"cv_id": cv_id, "job_text": SAMPLE_JOB_TEXT})
    ).json()
    await runner.wait(uuid.UUID(created["id"]))
    body = (await client.get(f"/applications/{created['id']}")).json()

    assert body["status"] == "failed"
    assert body["error"] == "Anthropic rate limit reached"
    assert body["job"] is not None  # progress before the failure is kept
    assert body["fit_report"] is None
    assert body["next_steps"] == ["fit_analysis"]


async def test_unknown_cv_returns_404(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    resp = await client.post(
        "/applications", json={"cv_id": str(uuid.uuid4()), "job_text": SAMPLE_JOB_TEXT}
    )
    assert resp.status_code == 404
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "body", [{}, {"cv_id": "nope", "job_text": SAMPLE_JOB_TEXT}, {"job_text": SAMPLE_JOB_TEXT}]
)
async def test_invalid_body_returns_422(client: AsyncClient, body: dict) -> None:
    assert (await client.post("/applications", json=body)).status_code == 422


async def test_short_job_text_returns_422(client: AsyncClient) -> None:
    cv_id = await upload_cv(client)
    resp = await client.post("/applications", json={"cv_id": cv_id, "job_text": "short"})
    assert resp.status_code == 422


async def test_too_long_job_text_returns_413(client: AsyncClient, test_settings) -> None:
    cv_id = await upload_cv(client)
    text = "x" * (test_settings.max_job_posting_chars + 1)
    resp = await client.post("/applications", json={"cv_id": cv_id, "job_text": text})
    assert resp.status_code == 413


async def test_get_unknown_application_returns_404(client: AsyncClient) -> None:
    assert (await client.get(f"/applications/{uuid.uuid4()}")).status_code == 404
