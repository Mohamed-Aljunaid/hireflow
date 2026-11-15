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


@dataclass
class LLMCall:
    system: str
    user: str
    output_model: type[BaseModel]


@dataclass
class FakeLLMClient:
    """Returns canned responses keyed by output model; records every call."""

    responses: dict[type[BaseModel], BaseModel | Exception] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)

    async def structured[T: BaseModel](self, *, system: str, user: str, output_model: type[T]) -> T:
        self.calls.append(LLMCall(system, user, output_model))
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
