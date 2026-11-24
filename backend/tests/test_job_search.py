from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_job_board
from app.services import job_search
from app.services.job_search import BASE_URL, JobSearchError, html_to_text, search_jobs
from app.services.pipeline_runner import PipelineRunner
from tests.conftest import SAMPLE_CV_TEXT, SAMPLE_JOB_TEXT

FUTURE, PAST = 4102444800, 1000000000


def job(title: str, locations: list[str] | None, **overrides: Any) -> dict[str, Any]:
    """Shaped like a real Himalayas listing."""
    slug = title.lower().replace(" ", "-")
    return {
        "title": title,
        "companyName": "Acme",
        "description": "<p>We build <b>agents</b>.</p><ul><li>Python</li></ul>",
        "locationRestrictions": locations,
        "pubDate": 1795107058,
        "expiryDate": FUTURE,
        "applicationLink": f"https://himalayas.app/jobs/{slug}?utm_source=api",
        "guid": f"https://himalayas.app/jobs/{slug}",
        "seniority": ["Senior"],
        **overrides,
    }


class Board:
    """Fake job board: canned reply, records requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply: Callable[[httpx.Request], httpx.Response] = self.jobs()

    def jobs(self, *jobs: dict, total: int | None = None) -> Callable:
        body = {"jobs": list(jobs), "totalCount": len(jobs) if total is None else total}
        return lambda _: httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.reply(request)

        return httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handle))


@pytest.fixture
def board() -> Board:
    job_search._cache.clear()
    return Board()


@pytest.fixture
def api(client: AsyncClient, board: Board) -> AsyncClient:
    async def fake_board() -> AsyncIterator[httpx.AsyncClient]:
        async with board.client() as http:
            yield http

    app: FastAPI = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_job_board] = fake_board
    return client


# ---------- parsing ----------


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("<p>A &amp; B</p><p>C</p>", "A & B\nC"),
        ("<ul><li>One</li><li><p>Two</p></li></ul>", "- One\n- Two"),
        ("<h3>Role</h3>x<br>y<script>alert(1)</script><style>p{}</style>", "Role\nx\ny"),
        ("plain   text", "plain text"),
    ],
)
def test_html_to_text(html: str, text: str) -> None:
    assert html_to_text(html) == text


async def test_listing_fields_and_order(board: Board) -> None:
    board.reply = board.jobs(
        job("Many", ["Saudi Arabia", "Egypt"]),
        job("Anywhere", []),
        job("Local", ["Saudi Arabia"]),
        job("Unknown", None),
        total=45,
    )
    async with board.client() as http:
        result = await search_jobs(http, "agentic AI", "SA", 2)

    assert [(j.title, j.location_scope) for j in result.listings] == [
        ("Local", "country_only"),
        ("Anywhere", "worldwide"),
        ("Unknown", "worldwide"),
        ("Many", "multi_country"),
    ]
    local = result.listings[0]
    assert local.posting_text == (
        "Local - Acme\nRemote (Saudi Arabia)\n\nWe build agents.\n- Python"
    )
    assert result.listings[-1].posting_text.splitlines()[1] == "Remote (2 countries)"
    assert local.apply_url == "https://himalayas.app/jobs/local?utm_source=api"  # unchanged
    assert local.source_url == "https://himalayas.app/jobs/local"
    assert local.published_at is not None and local.published_at.year == 2026
    assert (result.total, result.page, result.has_more) == (45, 2, True)
    url = board.requests[0].url
    assert (url.host, url.path) == ("himalayas.app", "/jobs/api/search")
    assert dict(url.params) == {"q": "agentic AI", "country": "SA", "page": "2"}


async def test_expired_and_malformed_listings_are_dropped(board: Board) -> None:
    board.reply = board.jobs(
        job("Expired", [], expiryDate=PAST),
        job("Evil", [], applicationLink="javascript:alert(1)"),
        {"title": "Incomplete"},
        job("No expiry", [], expiryDate=None),
    )
    async with board.client() as http:
        result = await search_jobs(http, "x1", "SA")
    assert [j.title for j in result.listings] == ["No expiry"]
    assert result.has_more is False


async def test_results_are_cached_then_refetched(
    board: Board, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job_search, "CACHE_SECONDS", 600)
    async with board.client() as http:
        await search_jobs(http, "AI", "SA")
        await search_jobs(http, "ai", "SA")
        assert len(board.requests) == 1
        await search_jobs(http, "AI", "AE")
        assert len(board.requests) == 2
        monkeypatch.setattr(job_search, "CACHE_SECONDS", 0)  # everything is stale
        await search_jobs(http, "AI", "SA")
    assert len(board.requests) == 3


async def test_cache_is_bounded(board: Board, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_search, "CACHE_MAX", 2)
    async with board.client() as http:
        for q in ("aa", "bb", "cc"):
            await search_jobs(http, q, "SA")
    assert len(job_search._cache) <= 2


# ---------- provider errors ----------


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        (httpx.Response(400, json={"errors": "Invalid country"}), 422),
        (httpx.Response(429), 503),
        (httpx.Response(500), 502),
        (httpx.Response(302, headers={"location": "https://evil.example"}), 502),
        (httpx.Response(200, text="<html>not json</html>"), 502),
        (httpx.Response(200, json={"jobs": "nope"}), 502),
    ],
)
async def test_provider_errors_map_to_status_and_are_not_cached(
    api: AsyncClient, board: Board, reply: httpx.Response, status: int
) -> None:
    board.reply = lambda _: reply
    assert (await api.get("/jobs/search", params={"q": "AI"})).status_code == status
    assert len(board.requests) == 1  # redirects are not followed
    board.reply = board.jobs(job("Back", []))
    assert (await api.get("/jobs/search", params={"q": "AI"})).status_code == 200


async def test_unreachable_provider(board: Board) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    board.reply = fail
    async with board.client() as http:
        with pytest.raises(JobSearchError, match="ConnectTimeout") as info:
            await search_jobs(http, "AI", "SA")
    assert info.value.status == 502


# ---------- API ----------


async def test_search_endpoint_defaults_to_saudi_arabia(api: AsyncClient, board: Board) -> None:
    board.reply = board.jobs(job("Local", ["Saudi Arabia"]))
    resp = await api.get("/jobs/search", params={"q": " agentic "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["listings"][0]["title"] == "Local"
    assert dict(board.requests[0].url.params) == {"q": "agentic", "country": "SA", "page": "1"}


@pytest.mark.parametrize(
    "params",
    [{}, {"q": "a"}, {"q": "x" * 101}, {"q": "AI", "country": "SAU"}, {"q": "AI", "page": 0}],
)
async def test_invalid_search_returns_422(api: AsyncClient, board: Board, params: dict) -> None:
    assert (await api.get("/jobs/search", params=params)).status_code == 422
    assert board.requests == []


async def test_picked_job_runs_the_pipeline_and_keeps_its_apply_link(
    api: AsyncClient, board: Board, runner: PipelineRunner
) -> None:
    board.reply = board.jobs(job("Local", ["Saudi Arabia"], description=f"<p>{SAMPLE_JOB_TEXT}"))
    listing = (await api.get("/jobs/search", params={"q": "AI"})).json()["listings"][0]
    cv = (await api.post("/cvs", files={"file": ("cv.txt", SAMPLE_CV_TEXT.encode())})).json()

    created = await api.post(
        "/applications",
        json={
            "cv_id": cv["id"],
            "job_text": listing["posting_text"],
            "apply_url": listing["apply_url"],
        },
    )
    assert created.status_code == 202, created.text
    for task in list(runner._tasks.values()):
        await task
    body = (await api.get(f"/applications/{created.json()['id']}")).json()
    assert body["status"] == "awaiting_approval"
    assert body["apply_url"] == listing["apply_url"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "himalayas.app/x"])
async def test_unsafe_apply_url_is_rejected(api: AsyncClient, url: str) -> None:
    cv = (await api.post("/cvs", files={"file": ("cv.txt", SAMPLE_CV_TEXT.encode())})).json()
    resp = await api.post(
        "/applications", json={"cv_id": cv["id"], "job_text": SAMPLE_JOB_TEXT, "apply_url": url}
    )
    assert resp.status_code == 422
