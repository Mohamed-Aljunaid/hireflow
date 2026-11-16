import uuid

from httpx import AsyncClient

from app.agents.schemas.cv import CVExtraction, ParsedCV
from app.core.llm import LLMRefusalError, LLMUnavailableError
from tests.conftest import SAMPLE_CV_TEXT
from tests.docs import make_docx, make_pdf
from tests.fakes import FakeLLMClient


async def upload(client: AsyncClient, name: str, data: bytes, ctype: str = "text/plain"):
    return await client.post("/cvs", files={"file": (name, data, ctype)})


async def test_upload_txt_returns_parsed_cv(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    resp = await upload(client, "cv.txt", SAMPLE_CV_TEXT.encode())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    parsed = ParsedCV.model_validate(body["parsed"])
    assert parsed.contact.name == "Jordan Rivera"
    assert parsed.experience[0].bullets[0].id == "exp-1.b1"
    assert body["filename"] == "cv.txt"
    assert body["content_type"] == "text/plain"
    # The extracted text, not the raw bytes, went to the LLM.
    assert "Led migration of a monolith" in fake_llm.calls[0].user


async def test_upload_pdf_and_docx(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    pdf = await upload(client, "cv.pdf", make_pdf(["Jordan Rivera PDF"]), "application/pdf")
    docx_resp = await upload(
        client, "cv.docx", make_docx(["Jordan Rivera DOCX"]), "application/octet-stream"
    )
    assert pdf.status_code == 201, pdf.text
    assert docx_resp.status_code == 201, docx_resp.text
    assert "Jordan Rivera PDF" in fake_llm.calls[0].user
    assert "Jordan Rivera DOCX" in fake_llm.calls[1].user


async def test_get_cv_round_trip(client: AsyncClient) -> None:
    created = (await upload(client, "cv.txt", SAMPLE_CV_TEXT.encode())).json()

    resp = await client.get(f"/cvs/{created['id']}")

    assert resp.status_code == 200
    assert resp.json() == created


async def test_get_missing_cv_returns_404(client: AsyncClient) -> None:
    resp = await client.get(f"/cvs/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_invalid_id_returns_422(client: AsyncClient) -> None:
    resp = await client.get("/cvs/not-a-uuid")
    assert resp.status_code == 422


async def test_unsupported_type_returns_415(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    resp = await upload(client, "photo.png", b"\x89PNG", "image/png")
    assert resp.status_code == 415
    assert fake_llm.calls == []


async def test_too_large_returns_413(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    resp = await upload(client, "cv.txt", b"a" * (64 * 1024 + 1))
    assert resp.status_code == 413
    assert fake_llm.calls == []


async def test_empty_document_returns_422(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    resp = await upload(client, "cv.txt", b"   \n  ")
    assert resp.status_code == 422
    assert fake_llm.calls == []


async def test_corrupt_pdf_returns_422(client: AsyncClient) -> None:
    resp = await upload(client, "cv.pdf", b"not a pdf", "application/pdf")
    assert resp.status_code == 422


async def test_llm_failure_returns_502_and_stores_nothing(
    client: AsyncClient, fake_llm: FakeLLMClient, session
) -> None:
    fake_llm.responses[CVExtraction] = LLMRefusalError("declined")

    resp = await upload(client, "cv.txt", SAMPLE_CV_TEXT.encode())

    assert resp.status_code == 502
    from sqlalchemy import func, select

    from app.db.models import CV

    assert (await session.scalar(select(func.count()).select_from(CV))) == 0


async def test_llm_unavailable_returns_503(client: AsyncClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.responses[CVExtraction] = LLMUnavailableError("no Anthropic credentials configured")

    resp = await upload(client, "cv.txt", SAMPLE_CV_TEXT.encode())

    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"]


async def test_missing_file_field_returns_422(client: AsyncClient) -> None:
    resp = await client.post("/cvs")
    assert resp.status_code == 422


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_cv_response_includes_evidence_index(client: AsyncClient) -> None:
    body = (await upload(client, "cv.txt", SAMPLE_CV_TEXT.encode())).json()
    expected = ParsedCV.model_validate(body["parsed"]).evidence_index()
    assert body["evidence"] == expected
    assert body["evidence"]["exp-1.b2"] == "Cut p95 latency 40% by introducing Redis caching."
