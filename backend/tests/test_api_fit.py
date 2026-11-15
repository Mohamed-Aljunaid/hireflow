import uuid

import pytest
from httpx import AsyncClient

from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitAssessment, FitReport, RequirementJudgement
from app.core.llm import LLMRefusalError, LLMUnavailableError
from tests.conftest import SAMPLE_CV_TEXT, SAMPLE_JOB_TEXT
from tests.fakes import FakeLLMClient


async def create_cv_and_job(client: AsyncClient) -> tuple[dict, dict]:
    cv = await client.post("/cvs", files={"file": ("cv.txt", SAMPLE_CV_TEXT.encode())})
    job = await client.post("/jobs", json={"text": SAMPLE_JOB_TEXT})
    assert cv.status_code == job.status_code == 201
    return cv.json(), job.json()


async def test_fit_returns_validated_report(
    client: AsyncClient, fake_llm: FakeLLMClient, test_settings
) -> None:
    cv, job = await create_cv_and_job(client)

    resp = await client.post("/fit", json={"cv_id": cv["id"], "job_id": job["id"]})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cv_id"] == cv["id"] and body["job_id"] == job["id"]
    report = FitReport.model_validate(body["report"])
    assert report.overall_score == 71
    assert [m.requirement_id for m in report.matches] == ["must-1", "must-2", "must-3", "nice-1"]

    fit_call = fake_llm.calls[-1]
    assert fit_call.output_model is FitAssessment
    assert fit_call.effort == test_settings.anthropic_analysis_effort
    # The stored CV and job, rendered with IDs, are what the analyst sees.
    assert "[exp-1.b1]" in fit_call.user and "[must-1]" in fit_call.user


async def test_fit_evidence_refs_exist_in_stored_cv(
    client: AsyncClient, fake_llm: FakeLLMClient
) -> None:
    cv, job = await create_cv_and_job(client)
    fake_llm.responses[FitAssessment] = FitAssessment(
        judgements=[
            RequirementJudgement(
                requirement_id="must-1", verdict="met", evidence_refs=["exp-1", "exp-404"],
                rationale="r",
            ),
            RequirementJudgement(
                requirement_id="must-3", verdict="met", evidence_refs=["invented"],
                rationale="r",
            ),
        ],
        summary="s",
    )  # fmt: skip

    report = FitReport.model_validate(
        (await client.post("/fit", json={"cv_id": cv["id"], "job_id": job["id"]})).json()["report"]
    )

    valid = set(ParsedCV.model_validate(cv["parsed"]).evidence_index())
    for m in report.matches:
        assert set(m.evidence_refs) <= valid
    assert report.matches[0].evidence_refs == ["exp-1"]
    assert report.matches[2].verdict == "not_met"
    assert report.warnings


@pytest.mark.parametrize("missing", ["cv", "job"])
async def test_fit_missing_resource_returns_404(
    client: AsyncClient, fake_llm: FakeLLMClient, missing: str
) -> None:
    cv, job = await create_cv_and_job(client)
    body = {"cv_id": cv["id"], "job_id": job["id"]}
    body[f"{missing}_id"] = str(uuid.uuid4())
    calls_before = len(fake_llm.calls)

    resp = await client.post("/fit", json=body)

    assert resp.status_code == 404
    assert missing.upper() in resp.json()["detail"].upper()
    assert len(fake_llm.calls) == calls_before


async def test_fit_invalid_body_returns_422(client: AsyncClient) -> None:
    assert (await client.post("/fit", json={"cv_id": "x"})).status_code == 422


@pytest.mark.parametrize(
    ("error", "status"),
    [(LLMRefusalError("declined"), 502), (LLMUnavailableError("down"), 503)],
)
async def test_fit_llm_errors(
    client: AsyncClient, fake_llm: FakeLLMClient, error: Exception, status: int
) -> None:
    cv, job = await create_cv_and_job(client)
    fake_llm.responses[FitAssessment] = error
    resp = await client.post("/fit", json={"cv_id": cv["id"], "job_id": job["id"]})
    assert resp.status_code == status
