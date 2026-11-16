import uuid

import pytest
from httpx import AsyncClient

from app.agents.schemas.content import CoverLetterDraft
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

    assert done["status"] == "awaiting_approval"
    assert done["error"] is None
    assert done["next_steps"] == ["fit_review"]
    assert done["pending_review"]["gate"] == "fit_review"
    assert done["pending_review"]["allowed_actions"] == ["approve", "edit", "reject"]
    assert done["pending_review"]["payload"]["fit_report"]["overall_score"] == 71
    assert done["reviews"] == []
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


# ---------- human-in-the-loop: POST /applications/{id}/resume ----------


async def paused_application(client: AsyncClient, runner: PipelineRunner) -> str:
    cv_id = await upload_cv(client)
    created = (
        await client.post("/applications", json={"cv_id": cv_id, "job_text": SAMPLE_JOB_TEXT})
    ).json()
    await runner.wait(uuid.UUID(created["id"]))
    return created["id"]


async def resume_and_wait(
    client: AsyncClient, runner: PipelineRunner, app_id: str, decision: dict
) -> tuple[dict, dict]:
    resp = await client.post(f"/applications/{app_id}/resume", json=decision)
    assert resp.status_code == 202, resp.text
    await runner.wait(uuid.UUID(app_id))
    return resp.json(), (await client.get(f"/applications/{app_id}")).json()


async def test_resume_approve(client: AsyncClient, runner: PipelineRunner) -> None:
    app_id = await paused_application(client, runner)

    accepted, final = await resume_and_wait(
        client, runner, app_id, {"action": "approve", "feedback": "Proceed"}
    )

    assert accepted["status"] == "running"
    assert accepted["pending_review"] is None
    # Drafting ran; now paused for the content review with everything to look at.
    assert final["status"] == "awaiting_approval"
    assert final["pending_review"]["gate"] == "content_review"
    assert final["pending_review"]["allowed_actions"] == ["approve", "edit", "regenerate", "reject"]
    assert len(final["tailored"]["bullets"]) == 4
    assert final["cover_letter"]["salutation"] == "Dear Northwind Labs Hiring Team,"
    assert final["company_brief"]["facts"][0]["id"] == "co-1"

    _, done = await resume_and_wait(client, runner, app_id, {"action": "approve"})

    assert done["status"] == "completed"
    assert done["pending_review"] is None
    assert done["next_steps"] == []
    assert [(r["gate"], r["action"], r["feedback"]) for r in done["reviews"]] == [
        ("fit_review", "approve", "Proceed"),
        ("content_review", "approve", None),
    ]


async def test_resume_content_edit(client: AsyncClient, runner: PipelineRunner) -> None:
    app_id = await paused_application(client, runner)
    await resume_and_wait(client, runner, app_id, {"action": "approve"})

    _, done = await resume_and_wait(
        client,
        runner,
        app_id,
        {"action": "edit", "text_edits": [{"id": "p-1", "text": "My own opening line."}]},
    )

    assert done["status"] == "completed"
    p1 = done["cover_letter"]["paragraphs"][0]
    assert (p1["text"], p1["author"]) == ("My own opening line.", "human")


async def test_resume_content_edit_unknown_id_returns_422(
    client: AsyncClient, runner: PipelineRunner
) -> None:
    app_id = await paused_application(client, runner)
    await resume_and_wait(client, runner, app_id, {"action": "approve"})

    resp = await client.post(
        f"/applications/{app_id}/resume",
        json={"action": "edit", "text_edits": [{"id": "p-42", "text": "x"}]},
    )

    assert resp.status_code == 422
    assert "p-42" in resp.json()["detail"]


async def test_resume_regenerate(
    client: AsyncClient, runner: PipelineRunner, fake_llm: FakeLLMClient
) -> None:
    app_id = await paused_application(client, runner)
    await resume_and_wait(client, runner, app_id, {"action": "approve"})

    _, again = await resume_and_wait(
        client, runner, app_id, {"action": "regenerate", "feedback": "More formal tone"}
    )

    assert again["status"] == "awaiting_approval"
    assert again["pending_review"]["gate"] == "content_review"
    assert "More formal tone" in fake_llm.calls_for(CoverLetterDraft)[-1].user


async def test_regenerate_not_allowed_at_fit_review(
    client: AsyncClient, runner: PipelineRunner
) -> None:
    app_id = await paused_application(client, runner)
    resp = await client.post(f"/applications/{app_id}/resume", json={"action": "regenerate"})
    assert resp.status_code == 422
    assert "not allowed at fit_review" in resp.json()["detail"]


async def test_resume_edit(client: AsyncClient, runner: PipelineRunner) -> None:
    app_id = await paused_application(client, runner)
    decision = {
        "action": "edit",
        "match_overrides": [
            {
                "requirement_id": "must-3",
                "verdict": "met",
                "evidence_refs": ["skill-5"],
                "note": "Reviewer judges the listed Docker experience sufficient here.",
            }
        ],
    }

    _, final = await resume_and_wait(client, runner, app_id, decision)

    assert final["status"] == "awaiting_approval"  # now at the content gate
    k8s = final["fit_report"]["matches"][2]
    assert (k8s["verdict"], k8s["source"], k8s["evidence_refs"]) == ("met", "human", ["skill-5"])
    assert final["fit_report"]["overall_score"] == 100
    assert final["reviews"][0]["overridden_requirements"] == ["must-3"]


async def test_resume_reject(client: AsyncClient, runner: PipelineRunner) -> None:
    app_id = await paused_application(client, runner)

    _, final = await resume_and_wait(
        client, runner, app_id, {"action": "reject", "feedback": "Skip this one"}
    )

    assert final["status"] == "rejected"
    assert final["next_steps"] == []
    assert final["reviews"][0]["action"] == "reject"


@pytest.mark.parametrize(
    ("decision", "detail"),
    [
        (
            {
                "action": "edit",
                "match_overrides": [
                    {"requirement_id": "must-3", "verdict": "met", "evidence_refs": ["invented"],
                     "note": "n"}
                ],
            },
            "invented",
        ),
        (
            {
                "action": "edit",
                "match_overrides": [
                    {"requirement_id": "must-3", "verdict": "met", "evidence_refs": [], "note": "n"}
                ],
            },
            "needs at least one CV reference",
        ),
    ],
)  # fmt: skip
async def test_resume_invalid_edit_returns_422_and_stays_paused(
    client: AsyncClient, runner: PipelineRunner, decision: dict, detail: str
) -> None:
    app_id = await paused_application(client, runner)

    resp = await client.post(f"/applications/{app_id}/resume", json=decision)

    assert resp.status_code == 422
    assert detail in resp.json()["detail"]
    body = (await client.get(f"/applications/{app_id}")).json()
    assert body["status"] == "awaiting_approval"
    assert body["pending_review"] is not None


@pytest.mark.parametrize(
    "decision",
    [{"action": "maybe"}, {"action": "edit"}, {"action": "approve", "match_overrides": [{}]}, {}],
)
async def test_resume_malformed_decision_returns_422(
    client: AsyncClient, runner: PipelineRunner, decision: dict
) -> None:
    app_id = await paused_application(client, runner)
    resp = await client.post(f"/applications/{app_id}/resume", json=decision)
    assert resp.status_code == 422


async def test_resume_twice_returns_409(client: AsyncClient, runner: PipelineRunner) -> None:
    app_id = await paused_application(client, runner)
    await resume_and_wait(client, runner, app_id, {"action": "approve"})
    await resume_and_wait(client, runner, app_id, {"action": "approve"})  # completed

    resp = await client.post(f"/applications/{app_id}/resume", json={"action": "approve"})

    assert resp.status_code == 409


async def test_resume_failed_application_returns_409(
    client: AsyncClient, runner: PipelineRunner, fake_llm: FakeLLMClient
) -> None:
    fake_llm.responses[FitAssessment] = LLMUnavailableError("down")
    app_id = await paused_application(client, runner)  # actually fails before the gate

    resp = await client.post(f"/applications/{app_id}/resume", json={"action": "approve"})

    assert resp.status_code == 409


async def test_resume_unknown_application_returns_404(client: AsyncClient) -> None:
    resp = await client.post(f"/applications/{uuid.uuid4()}/resume", json={"action": "approve"})
    assert resp.status_code == 404
