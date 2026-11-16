"""Test doubles. No test talks to the real Anthropic API."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agents.schemas.content import ClaimCheck, ClaimFinding
from app.core.mock_llm import (  # noqa: F401  (re-exported for the tests)
    UNIT_ID,
    all_supported,
    demo_responses,
    sample_company_research,
    sample_cover_letter_draft,
    sample_extraction,
    sample_fit_assessment,
    sample_job_extraction,
    sample_tailoring_draft,
)


@dataclass
class LLMCall:
    system: str
    user: str
    output_model: type[BaseModel]
    effort: str | None = None


@dataclass
class FakeLLMClient:
    """Returns canned responses keyed by output model; records every call.

    A response may be a model, an exception, a callable(user_prompt) -> either, or a
    list of those consumed in order (the last one repeats).
    """

    responses: dict[type[BaseModel], Any] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)

    async def structured[T: BaseModel](
        self, *, system: str, user: str, output_model: type[T], effort: str | None = None
    ) -> T:
        self.calls.append(LLMCall(system, user, output_model, effort))
        response = self.responses[output_model]
        if isinstance(response, list):
            response = response.pop(0) if len(response) > 1 else response[0]
        if callable(response) and not isinstance(response, BaseModel):
            response = response(user)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, output_model)
        return response

    def calls_for(self, output_model: type[BaseModel]) -> list[LLMCall]:
        return [c for c in self.calls if c.output_model is output_model]


class BlockingLLMClient(FakeLLMClient):
    """Hangs forever on `block_on`, to simulate a process dying mid-step."""

    def __init__(self, block_on: type[BaseModel], **kw) -> None:
        super().__init__(**kw)
        self.block_on = block_on
        self.reached = asyncio.Event()

    async def structured[T: BaseModel](
        self, *, system: str, user: str, output_model: type[T], effort: str | None = None
    ) -> T:
        if output_model is self.block_on:
            self.calls.append(LLMCall(system, user, output_model, effort))
            self.reached.set()
            await asyncio.Event().wait()  # never set: only cancellation ends this
        return await super().structured(
            system=system, user=user, output_model=output_model, effort=effort
        )


def default_responses() -> dict[type[BaseModel], Any]:
    return dict(demo_responses())  # fresh dict: tests mutate it


def flag_units(flags: dict[str, str]):
    """Claim-check fake: units in `flags` are unsupported (with that problem)."""

    def check(user: str) -> ClaimCheck:
        return ClaimCheck(
            findings=[
                ClaimFinding(unit_id=u, supported=u not in flags,
                             problems=[flags[u]] if u in flags else [])
                for u in UNIT_ID.findall(user)
            ]
        )  # fmt: skip

    return check


async def seed_application(session_factory, job_text: str = "Senior Python Engineer " * 5):
    """Insert a CV and an application row; return the application id."""
    from app.agents.schemas.cv import ParsedCV
    from app.services import application_repository, cv_repository

    async with session_factory() as session:
        cv = await cv_repository.create_cv(
            session,
            filename="cv.txt",
            content_type="text/plain",
            raw_text="raw",
            parsed=ParsedCV.from_extraction(sample_extraction()),
        )
        application = await application_repository.create_application(
            session, cv_id=cv.id, job_text=job_text
        )
        return application.id
