"""Find remote jobs through the Himalayas public API (free, no key, full descriptions).

Their terms: use applicationLink unchanged, link back to every listing, and don't pass
listings on to other job boards. https://himalayas.app/api
"""

import logging
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

BASE_URL = "https://himalayas.app"
PAGE_SIZE = 20  # fixed by the provider
CACHE_SECONDS = 600
CACHE_MAX = 256

# Rendered as links, so never javascript: or data:. Kept as str: the terms say "unchanged".
WebUrl = Annotated[str, Field(pattern=r"^https?://", max_length=2048)]
LocationScope = Literal["country_only", "worldwide", "multi_country"]
_SCOPE_ORDER: dict[LocationScope, int] = {"country_only": 0, "worldwide": 1, "multi_country": 2}


class JobSearchError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class JobListing(BaseModel):
    title: str
    company: str
    posting_text: str = Field(description="Plain text, ready for the pipeline.")
    location_scope: LocationScope
    apply_url: WebUrl
    source_url: WebUrl
    published_at: datetime | None
    expires_at: datetime | None


class JobSearchResult(BaseModel):
    listings: list[JobListing]
    total: int
    page: int
    has_more: bool


class _RawJob(BaseModel):
    title: str
    company: str = Field(alias="companyName")
    description: str
    locations: list[str] | None = Field(None, alias="locationRestrictions")
    published_at: datetime | None = Field(None, alias="pubDate")
    expires_at: datetime | None = Field(None, alias="expiryDate")
    apply_url: WebUrl = Field(alias="applicationLink")
    source_url: WebUrl = Field(alias="guid")


class _RawPage(BaseModel):
    jobs: list[dict]
    total: int = Field(alias="totalCount")


class _HTMLText(HTMLParser):
    BLOCKS = frozenset(
        {"p", "div", "br", "ul", "ol", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    )

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._hidden += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._hidden -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    text = "\n".join(line for line in lines if line)
    return re.sub(r"(?m)^-\n", "- ", text)  # <li><p>x</p></li>


def _listing(raw: _RawJob) -> JobListing:
    locations = raw.locations or []
    scope: LocationScope
    if not locations:
        scope, where = "worldwide", "worldwide"
    elif len(locations) == 1:
        scope, where = "country_only", locations[0]
    else:
        scope, where = "multi_country", f"{len(locations)} countries"
    return JobListing(
        posting_text=f"{raw.title} - {raw.company}\nRemote ({where})\n\n"
        + html_to_text(raw.description),
        location_scope=scope,
        **raw.model_dump(exclude={"locations", "description"}),
    )


_cache: dict[tuple[str, str, int], tuple[float, JobSearchResult]] = {}


async def search_jobs(
    http: httpx.AsyncClient, q: str, country: str, page: int = 1
) -> JobSearchResult:
    """One provider page, country-only jobs first (the order is within the page)."""
    key = (q.lower(), country, page)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    try:
        resp = await http.get("/jobs/api/search", params={"q": q, "country": country, "page": page})
    except httpx.HTTPError as exc:
        raise JobSearchError(f"could not reach the job board ({type(exc).__name__})") from exc
    if resp.status_code == 400:
        raise JobSearchError("the job board rejected this search; check the country", 422)
    if resp.status_code == 429:
        raise JobSearchError("the job board is rate limiting us; try again in a minute", 503)
    if resp.status_code != 200:
        raise JobSearchError(f"the job board returned an error ({resp.status_code})")
    try:
        raw_page = _RawPage.model_validate_json(resp.content)
    except ValidationError as exc:
        raise JobSearchError("the job board sent an unexpected response") from exc

    now = datetime.now(UTC)
    listings = []
    for item in raw_page.jobs:
        try:
            raw = _RawJob.model_validate(item)
        except ValidationError as exc:  # one bad listing must not hide the rest
            logger.warning("skipped malformed listing: %s", exc)
            continue
        if raw.expires_at is None or raw.expires_at > now:
            listings.append(_listing(raw))
    listings.sort(key=lambda j: _SCOPE_ORDER[j.location_scope])  # stable: keeps relevance

    result = JobSearchResult(
        listings=listings,
        total=raw_page.total,
        page=page,
        has_more=page * PAGE_SIZE < raw_page.total,
    )
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.monotonic(), result)
    return result
