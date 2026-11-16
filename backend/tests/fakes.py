"""Test doubles. No test talks to the real Anthropic API."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.agents.schemas.content import (
    BulletDraft,
    ClaimCheck,
    ClaimFinding,
    CoverLetterDraft,
    ParagraphDraft,
    TailoringDraft,
)
from app.agents.schemas.cv import (
    ContactInfo,
    CVExtraction,
    EducationExtraction,
    ExperienceExtraction,
    ProjectExtraction,
)
from app.agents.schemas.fit import FitAssessment, GapClaim, RequirementJudgement, StrengthClaim
from app.agents.schemas.job import JobPostingExtraction, RequirementExtraction
from app.agents.schemas.research import CompanyResearch, FactExtraction


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


def sample_extraction() -> CVExtraction:
    return CVExtraction(
        contact=ContactInfo(
            name="Jordan Rivera",
            email="jordan.rivera@example.com",
            phone="+1 555 0100",
            location="Austin, TX",
            links=["https://github.com/jrivera-example"],
        ),
        summary="Backend engineer with 6 years building Python APIs.",
        experience=[
            ExperienceExtraction(
                title="Senior Backend Engineer",
                company="Acme Analytics",
                location="Remote",
                start_date="Mar 2022",
                end_date="Present",
                bullets=[
                    "Led migration of a monolith to FastAPI microservices serving 2M requests/day.",
                    "Cut p95 latency 40% by introducing Redis caching.",
                ],
            ),
            ExperienceExtraction(
                title="Software Engineer",
                company="Brightside Health",
                start_date="Jun 2019",
                end_date="Feb 2022",
                bullets=["Built HL7 ingestion pipeline in Python and PostgreSQL."],
            ),
        ],
        projects=[
            ProjectExtraction(
                name="pg-snapshots",
                description="Open-source Postgres snapshot tool.",
                bullets=["300+ GitHub stars."],
            )
        ],
        education=[
            EducationExtraction(
                institution="University of Texas at Austin",
                degree="BSc",
                field_of_study="Computer Science",
                end_date="2019",
            )
        ],
        skills=["Python", "FastAPI", "PostgreSQL", "Redis", "Docker"],
        certifications=["AWS Certified Developer"],
        languages=["English", "Spanish"],
    )


def sample_job_extraction() -> JobPostingExtraction:
    return JobPostingExtraction(
        title="Senior Python Engineer",
        company="Northwind Labs",
        location="Remote (US)",
        remote_policy="remote",
        employment_type="full-time",
        seniority="senior",
        salary_range="$160k-$190k",
        must_haves=[
            RequirementExtraction(
                text="5+ years of Python backend experience", category="experience"
            ),
            RequirementExtraction(text="FastAPI or similar async framework", category="skill"),
            RequirementExtraction(text="Kubernetes in production", category="skill"),
        ],
        nice_to_haves=[
            RequirementExtraction(text="Open-source contributions", category="other"),
        ],
        responsibilities=["Design and own backend services", "Mentor engineers"],
        keywords=["Python", "FastAPI", "Kubernetes", "PostgreSQL"],
    )


# CV IDs from sample_extraction(): exp-1, exp-1.b1, exp-1.b2, exp-2, exp-2.b1, proj-1,
# proj-1.b1, summary, edu-1, skill-1..5, cert-1, lang-1..2.
# Job IDs from sample_job_extraction(): must-1, must-2, must-3, nice-1.
def sample_fit_assessment() -> FitAssessment:
    return FitAssessment(
        judgements=[
            RequirementJudgement(
                requirement_id="must-1",
                verdict="met",
                evidence_refs=["exp-1", "exp-2", "summary"],
                rationale="Python backend roles since Jun 2019, over 5 years.",
            ),
            RequirementJudgement(
                requirement_id="must-2",
                verdict="met",
                evidence_refs=["exp-1.b1", "skill-2"],
                rationale="Led a FastAPI microservices migration.",
            ),
            RequirementJudgement(
                requirement_id="must-3",
                verdict="not_met",
                evidence_refs=[],
                rationale="No Kubernetes on the CV; Docker only.",
            ),
            RequirementJudgement(
                requirement_id="nice-1",
                verdict="met",
                evidence_refs=["proj-1", "proj-1.b1"],
                rationale="Maintains pg-snapshots with 300+ stars.",
            ),
        ],
        strengths=[
            StrengthClaim(text="Production FastAPI at scale", evidence_refs=["exp-1.b1"]),
        ],
        gaps=[GapClaim(text="No Kubernetes experience", requirement_ids=["must-3"])],
        summary="Strong Python/FastAPI fit; Kubernetes is the main gap.",
    )


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
    from app.agents.schemas.cv import CVExtraction

    return {
        CVExtraction: sample_extraction(),
        JobPostingExtraction: sample_job_extraction(),
        CompanyResearch: sample_company_research(),
        FitAssessment: sample_fit_assessment(),
        TailoringDraft: sample_tailoring_draft(),
        CoverLetterDraft: sample_cover_letter_draft(),
        ClaimCheck: all_supported,
    }


def sample_company_research() -> CompanyResearch:
    return CompanyResearch(
        summary="Northwind Labs is hiring a senior engineer to own its backend services.",
        facts=[
            FactExtraction(
                text="The role is remote within the US.", category="culture",
                source_id="job_posting",
            ),
        ],
    )  # fmt: skip


# Faithful to sample_extraction(): every bullet/paragraph is supported by its refs.
def sample_tailoring_draft() -> TailoringDraft:
    return TailoringDraft(
        bullets=[
            BulletDraft(
                text="Led migration of a monolith to FastAPI microservices serving "
                "2M requests/day.",
                source_cv_refs=["exp-1.b1"], requirement_ids=["must-2"],
            ),
            BulletDraft(
                text="Cut p95 latency 40% by introducing Redis caching.",
                source_cv_refs=["exp-1.b2"],
            ),
            BulletDraft(
                text="Built an HL7 ingestion pipeline in Python and PostgreSQL.",
                source_cv_refs=["exp-2.b1"], requirement_ids=["must-1"],
            ),
            BulletDraft(
                text="Maintain pg-snapshots, an open-source Postgres tool with 300+ GitHub stars.",
                source_cv_refs=["proj-1", "proj-1.b1"], requirement_ids=["nice-1"],
            ),
        ]
    )  # fmt: skip


def sample_cover_letter_draft() -> CoverLetterDraft:
    return CoverLetterDraft(
        salutation="Dear Northwind Labs Hiring Team,",
        paragraphs=[
            ParagraphDraft(
                text="At Acme Analytics I led the migration of a monolith to FastAPI "
                "microservices serving 2M requests/day.",
                source_cv_refs=["exp-1", "exp-1.b1"],
            ),
            ParagraphDraft(
                text="Before that, at Brightside Health, I built an HL7 ingestion pipeline "
                "in Python and PostgreSQL.",
                source_cv_refs=["exp-2", "exp-2.b1"],
            ),
            ParagraphDraft(
                text="I am glad the role is remote within the US, and would welcome a "
                "conversation.",
                company_fact_refs=["co-1"],
            ),
        ],
        closing="Best regards,\nJordan Rivera",
    )


UNIT_ID = re.compile(r"^\[((?:tb|p)-\d+)\]", re.MULTILINE)


def all_supported(user: str) -> ClaimCheck:
    """Claim-check fake: every unit in the prompt is supported."""
    return ClaimCheck(
        findings=[ClaimFinding(unit_id=u, supported=True) for u in UNIT_ID.findall(user)]
    )


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
