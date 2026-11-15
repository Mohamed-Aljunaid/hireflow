from app.agents.schemas.cv import ContactInfo, CVExtraction, ParsedCV
from tests.fakes import sample_extraction


def test_evidence_index_ids() -> None:
    index = ParsedCV.from_extraction(sample_extraction()).evidence_index()

    assert set(index) == {
        "summary",
        "exp-1", "exp-1.b1", "exp-1.b2",
        "exp-2", "exp-2.b1",
        "proj-1", "proj-1.b1",
        "edu-1",
        "skill-1", "skill-2", "skill-3", "skill-4", "skill-5",
        "cert-1",
        "lang-1", "lang-2",
    }  # fmt: skip
    assert index["exp-1"] == "Senior Backend Engineer at Acme Analytics (Mar 2022 - Present)"
    assert index["exp-2.b1"] == "Built HL7 ingestion pipeline in Python and PostgreSQL."
    assert index["proj-1"] == "pg-snapshots: Open-source Postgres snapshot tool."
    assert index["edu-1"] == "BSc, Computer Science, University of Texas at Austin, 2019"
    assert index["skill-3"] == "PostgreSQL"
    assert index["cert-1"] == "AWS Certified Developer"


def test_evidence_index_is_stable_across_serialisation() -> None:
    cv = ParsedCV.from_extraction(sample_extraction())
    reloaded = ParsedCV.model_validate(cv.model_dump(mode="json"))
    assert reloaded.evidence_index() == cv.evidence_index()


def test_render_with_ids_contains_every_evidence_id() -> None:
    cv = ParsedCV.from_extraction(sample_extraction())
    rendered = cv.render_with_ids()
    for evidence_id, text in cv.evidence_index().items():
        assert f"[{evidence_id}] {text}" in rendered


def test_minimal_cv() -> None:
    cv = ParsedCV.from_extraction(CVExtraction(contact=ContactInfo(name="A. Person")))
    assert cv.evidence_index() == {}
    assert cv.render_with_ids() == "Candidate: A. Person"
