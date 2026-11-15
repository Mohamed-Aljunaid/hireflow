import pytest

from app.agents.prompts import CV_PARSER_SYSTEM
from app.agents.schemas.cv import CVExtraction, ParsedCV
from app.core.llm import LLMRefusalError
from app.services.cv_parser import parse_cv
from tests.fakes import FakeLLMClient, sample_extraction


async def test_parse_cv_calls_llm_with_structured_model(fake_llm: FakeLLMClient) -> None:
    parsed = await parse_cv("Jordan Rivera\nSenior Backend Engineer", fake_llm)

    assert isinstance(parsed, ParsedCV)
    [call] = fake_llm.calls
    assert call.output_model is CVExtraction
    assert call.system == CV_PARSER_SYSTEM
    assert call.user == "<cv>\nJordan Rivera\nSenior Backend Engineer\n</cv>"


async def test_parse_cv_propagates_llm_errors() -> None:
    llm = FakeLLMClient(responses={CVExtraction: LLMRefusalError("nope")})
    with pytest.raises(LLMRefusalError):
        await parse_cv("text", llm)


def test_from_extraction_assigns_stable_ids() -> None:
    parsed = ParsedCV.from_extraction(sample_extraction())

    assert [e.id for e in parsed.experience] == ["exp-1", "exp-2"]
    assert [b.id for b in parsed.experience[0].bullets] == ["exp-1.b1", "exp-1.b2"]
    assert parsed.experience[1].bullets[0].id == "exp-2.b1"
    assert parsed.projects[0].id == "proj-1"
    assert parsed.projects[0].bullets[0].id == "proj-1.b1"


def test_from_extraction_preserves_content() -> None:
    extraction = sample_extraction()
    parsed = ParsedCV.from_extraction(extraction)

    assert parsed.contact == extraction.contact
    assert parsed.skills == extraction.skills
    assert parsed.education == extraction.education
    assert parsed.experience[0].company == "Acme Analytics"
    assert [b.text for b in parsed.experience[0].bullets] == extraction.experience[0].bullets


def test_bullet_index_covers_experience_and_projects() -> None:
    index = ParsedCV.from_extraction(sample_extraction()).bullet_index()
    assert set(index) == {"exp-1.b1", "exp-1.b2", "exp-2.b1", "proj-1.b1"}
    assert index["proj-1.b1"].text == "300+ GitHub stars."


def test_parsed_cv_round_trips_through_json() -> None:
    parsed = ParsedCV.from_extraction(sample_extraction())
    assert ParsedCV.model_validate(parsed.model_dump(mode="json")) == parsed
