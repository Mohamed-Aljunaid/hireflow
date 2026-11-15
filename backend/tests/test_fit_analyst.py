import pytest

from app.agents.fit_analyst import DOWNGRADED, NOT_ASSESSED, analyse_fit, build_fit_report
from app.agents.prompts import FIT_ANALYST_SYSTEM
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import (
    FitAssessment,
    FitReport,
    GapClaim,
    RequirementJudgement,
    StrengthClaim,
)
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.llm import LLMRefusalError
from tests.fakes import (
    FakeLLMClient,
    sample_extraction,
    sample_fit_assessment,
    sample_job_extraction,
)


@pytest.fixture
def cv() -> ParsedCV:
    return ParsedCV.from_extraction(sample_extraction())


@pytest.fixture
def job() -> JobPosting:
    return JobPosting.from_extraction(sample_job_extraction())


def judge(req: str, verdict: str, refs: list[str], why: str = "because") -> RequirementJudgement:
    return RequirementJudgement(
        requirement_id=req, verdict=verdict, evidence_refs=refs, rationale=why
    )


def assessment(*judgements: RequirementJudgement, **kw) -> FitAssessment:
    return FitAssessment(judgements=list(judgements), summary="s", **kw)


def assert_all_evidence_real(report: FitReport, cv: ParsedCV, job: JobPosting) -> None:
    """The Phase 2 guarantee: every cited CV ID exists, and claims have evidence."""
    valid = set(cv.evidence_index())
    assert [m.requirement_id for m in report.matches] == [r.id for r in job.requirements]
    for m in report.matches:
        assert set(m.evidence_refs) <= valid, m
        if m.verdict != "not_met":
            assert m.evidence_refs, m
    for s in report.strengths:
        assert s.evidence_refs and set(s.evidence_refs) <= valid
    req_ids = {r.id for r in job.requirements}
    for g in report.gaps:
        assert set(g.requirement_ids) <= req_ids


# ---------- analyse_fit (LLM wiring) ----------


async def test_analyse_fit_sends_ids_and_returns_report(
    fake_llm: FakeLLMClient, cv: ParsedCV, job: JobPosting
) -> None:
    report = await analyse_fit(cv, job, fake_llm, effort="high")

    [call] = fake_llm.calls
    assert call.output_model is FitAssessment
    assert call.system == FIT_ANALYST_SYSTEM
    assert call.effort == "high"
    assert "[must-3] (skill) Kubernetes in production" in call.user
    assert "[exp-1.b1] Led migration of a monolith" in call.user
    assert "[skill-2] FastAPI" in call.user
    assert report.warnings == []
    assert_all_evidence_real(report, cv, job)


async def test_analyse_fit_propagates_llm_errors(cv: ParsedCV, job: JobPosting) -> None:
    llm = FakeLLMClient(responses={FitAssessment: LLMRefusalError("no")})
    with pytest.raises(LLMRefusalError):
        await analyse_fit(cv, job, llm)


# ---------- scoring ----------


def test_score_from_sample(cv: ParsedCV, job: JobPosting) -> None:
    report = build_fit_report(sample_fit_assessment(), job=job, cv=cv)
    # must: met, met, not_met (weight 2 each); nice: met (weight 1) -> 5/7
    assert report.overall_score == 71
    assert report.must_have_score == 67
    assert report.nice_to_have_score == 100
    assert [m.verdict for m in report.matches] == ["met", "met", "not_met", "met"]


@pytest.mark.parametrize(
    ("verdicts", "overall", "must", "nice"),
    [
        (["met", "met", "met", "met"], 100, 100, 100),
        (["not_met", "not_met", "not_met", "not_met"], 0, 0, 0),
        (["partial", "partial", "partial", "partial"], 50, 50, 50),
        (["met", "met", "met", "not_met"], 86, 100, 0),  # 6/7
        (["not_met", "not_met", "not_met", "met"], 14, 0, 100),  # 1/7
    ],
)
def test_score_weights_must_haves_double(
    cv: ParsedCV, job: JobPosting, verdicts: list[str], overall: int, must: int, nice: int
) -> None:
    ids = ["must-1", "must-2", "must-3", "nice-1"]
    a = assessment(*(judge(i, v, ["exp-1"]) for i, v in zip(ids, verdicts, strict=True)))
    report = build_fit_report(a, job=job, cv=cv)
    assert (report.overall_score, report.must_have_score, report.nice_to_have_score) == (
        overall,
        must,
        nice,
    )


def test_no_requirements_gives_no_score(cv: ParsedCV) -> None:
    empty_job = JobPosting.from_extraction(JobPostingExtraction(title="Engineer"))
    report = build_fit_report(assessment(), job=empty_job, cv=cv)
    assert report.overall_score is None
    assert report.must_have_score is None
    assert report.nice_to_have_score is None
    assert report.matches == []


def test_only_must_haves_gives_no_nice_score(cv: ParsedCV) -> None:
    extraction = sample_job_extraction()
    extraction.nice_to_haves = []
    only_must = JobPosting.from_extraction(extraction)
    report = build_fit_report(sample_fit_assessment(), job=only_must, cv=cv)
    assert report.nice_to_have_score is None
    assert report.must_have_score == report.overall_score == 67


# ---------- evidence enforcement ----------


def test_invented_refs_are_dropped(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(
        judge("must-1", "met", ["exp-1", "exp-9", "skill-99"]),
        judge("must-2", "met", ["exp-1.b1"]),
        judge("must-3", "not_met", []),
        judge("nice-1", "met", ["proj-1"]),
    )
    report = build_fit_report(a, job=job, cv=cv)

    assert report.matches[0].evidence_refs == ["exp-1"]
    assert report.matches[0].verdict == "met"
    assert any("exp-9" in w and "skill-99" in w for w in report.warnings)
    assert_all_evidence_real(report, cv, job)


@pytest.mark.parametrize("verdict", ["met", "partial"])
def test_claim_without_valid_evidence_is_downgraded(
    cv: ParsedCV, job: JobPosting, verdict: str
) -> None:
    a = assessment(
        judge("must-1", verdict, ["made-up-1"], why="Has Kubernetes."),
        judge("must-2", "met", []),
        judge("must-3", "not_met", []),
        judge("nice-1", "met", ["proj-1"]),
    )
    report = build_fit_report(a, job=job, cv=cv)

    m1, m2 = report.matches[0], report.matches[1]
    assert m1.verdict == "not_met" and m1.evidence_refs == []
    assert m1.rationale == DOWNGRADED + "Has Kubernetes."
    assert m2.verdict == "not_met"
    assert sum("set to not_met" in w for w in report.warnings) == 2
    assert_all_evidence_real(report, cv, job)


def test_not_met_keeps_valid_related_refs(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(judge("must-3", "not_met", ["skill-5"], why="Docker but no Kubernetes."))
    report = build_fit_report(a, job=job, cv=cv)
    assert report.matches[2].evidence_refs == ["skill-5"]


def test_duplicate_refs_are_collapsed(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(judge("must-1", "met", ["exp-1", "exp-1", "exp-2", "exp-1"]))
    report = build_fit_report(a, job=job, cv=cv)
    assert report.matches[0].evidence_refs == ["exp-1", "exp-2"]


def test_unknown_and_duplicate_requirements_are_ignored(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(
        judge("must-1", "met", ["exp-1"], why="first"),
        judge("must-1", "not_met", [], why="second"),
        judge("must-42", "met", ["exp-1"]),
    )
    report = build_fit_report(a, job=job, cv=cv)

    assert report.matches[0].rationale == "first"
    assert len(report.matches) == 4
    assert any("duplicate" in w and "must-1" in w for w in report.warnings)
    assert any("unknown requirement 'must-42'" in w for w in report.warnings)


def test_missing_requirements_are_filled_as_not_met(cv: ParsedCV, job: JobPosting) -> None:
    report = build_fit_report(assessment(judge("nice-1", "met", ["proj-1"])), job=job, cv=cv)

    assert [m.requirement_id for m in report.matches] == ["must-1", "must-2", "must-3", "nice-1"]
    for m in report.matches[:3]:
        assert m.verdict == "not_met" and m.rationale == NOT_ASSESSED
    assert sum("not assessed" in w for w in report.warnings) == 3


def test_matches_follow_job_order_and_carry_requirement_text(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(
        judge("nice-1", "met", ["proj-1"]),
        judge("must-3", "not_met", []),
        judge("must-1", "met", ["exp-1"]),
        judge("must-2", "met", ["skill-2"]),
    )
    report = build_fit_report(a, job=job, cv=cv)
    assert [m.requirement_id for m in report.matches] == ["must-1", "must-2", "must-3", "nice-1"]
    assert report.matches[2].requirement_text == "Kubernetes in production"
    assert report.matches[3].importance == "nice"


def test_strengths_without_valid_evidence_are_dropped(cv: ParsedCV, job: JobPosting) -> None:
    a = assessment(
        strengths=[
            StrengthClaim(text="Real", evidence_refs=["exp-1.b2", "nope"]),
            StrengthClaim(text="Invented", evidence_refs=["exp-7.b1"]),
            StrengthClaim(text="Uncited", evidence_refs=[]),
        ],
        gaps=[GapClaim(text="K8s", requirement_ids=["must-3", "must-99"])],
    )
    report = build_fit_report(a, job=job, cv=cv)

    assert [s.text for s in report.strengths] == ["Real"]
    assert report.strengths[0].evidence_refs == ["exp-1.b2"]
    assert report.gaps[0].requirement_ids == ["must-3"]
    assert sum("Dropped strength" in w for w in report.warnings) == 2


def test_adversarial_assessment_still_yields_only_real_evidence(
    cv: ParsedCV, job: JobPosting
) -> None:
    """Everything wrong at once; the report must still satisfy the guarantee."""
    a = assessment(
        judge("must-1", "met", ["EXP-1", "exp-1 ", "experience-1"]),  # near-misses
        judge("must-2", "partial", ["skill-6", "skill-0"]),  # out of range
        judge("must-2", "met", ["exp-1.b1"]),  # duplicate
        judge("must-3", "met", ["exp-1.b3"]),  # bullet that doesn't exist
        judge("bogus", "met", ["exp-1"]),
        strengths=[StrengthClaim(text="x", evidence_refs=["cert-2"])],
        gaps=[GapClaim(text="y", requirement_ids=["nice-2"])],
    )
    report = build_fit_report(a, job=job, cv=cv)

    assert_all_evidence_real(report, cv, job)
    assert all(m.verdict == "not_met" for m in report.matches)
    assert report.overall_score == 0
    assert report.strengths == []
