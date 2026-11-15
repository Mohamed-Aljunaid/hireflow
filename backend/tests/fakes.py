"""Test doubles. No test talks to the real Anthropic API."""

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.agents.schemas.cv import (
    ContactInfo,
    CVExtraction,
    EducationExtraction,
    ExperienceExtraction,
    ProjectExtraction,
)
from app.agents.schemas.fit import FitAssessment, GapClaim, RequirementJudgement, StrengthClaim
from app.agents.schemas.job import JobPostingExtraction, RequirementExtraction


@dataclass
class LLMCall:
    system: str
    user: str
    output_model: type[BaseModel]
    effort: str | None = None


@dataclass
class FakeLLMClient:
    """Returns canned responses keyed by output model; records every call."""

    responses: dict[type[BaseModel], BaseModel | Exception] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)

    async def structured[T: BaseModel](
        self, *, system: str, user: str, output_model: type[T], effort: str | None = None
    ) -> T:
        self.calls.append(LLMCall(system, user, output_model, effort))
        response = self.responses[output_model]
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, output_model)
        return response


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
