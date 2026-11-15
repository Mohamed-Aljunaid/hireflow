import pytest
from pydantic import ValidationError

from app.agents.fit_analyst import build_fit_report
from app.agents.review import ReviewValidationError, apply_fit_overrides, check_action_allowed
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.agents.schemas.review import MatchOverride, ReviewDecision
from tests.fakes import sample_extraction, sample_fit_assessment, sample_job_extraction


@pytest.fixture
def cv() -> ParsedCV:
    return ParsedCV.from_extraction(sample_extraction())


@pytest.fixture
def report(cv: ParsedCV) -> FitReport:
    job = JobPosting.from_extraction(sample_job_extraction())
    return build_fit_report(sample_fit_assessment(), job=job, cv=cv)


def override(req: str, verdict: str, refs: list[str], note: str = "n") -> MatchOverride:
    return MatchOverride(requirement_id=req, verdict=verdict, evidence_refs=refs, note=note)


# ---------- ReviewDecision shape ----------


def test_approve_and_reject_need_no_overrides() -> None:
    ReviewDecision(action="approve")
    ReviewDecision(action="reject", feedback="not for me")


def test_edit_requires_overrides() -> None:
    with pytest.raises(ValidationError, match="at least one match override"):
        ReviewDecision(action="edit")


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_overrides_only_with_edit(action: str) -> None:
    with pytest.raises(ValidationError, match="cannot carry match overrides"):
        ReviewDecision(action=action, match_overrides=[override("must-1", "met", ["exp-1"])])


def test_duplicate_override_rejected() -> None:
    with pytest.raises(ValidationError, match="at most once"):
        ReviewDecision(
            action="edit",
            match_overrides=[
                override("must-1", "met", ["exp-1"]),
                override("must-1", "not_met", []),
            ],
        )


@pytest.mark.parametrize("action", ["regenerate", "approved", ""])
def test_unknown_action_rejected(action: str) -> None:
    with pytest.raises(ValidationError):
        ReviewDecision.model_validate({"action": action})


def test_note_is_required_for_overrides() -> None:
    with pytest.raises(ValidationError):
        MatchOverride(requirement_id="must-1", verdict="met", evidence_refs=["exp-1"], note="")


def test_check_action_allowed() -> None:
    check_action_allowed("fit_review", ReviewDecision(action="approve"))


# ---------- apply_fit_overrides ----------


def test_override_rescores_and_marks_source(cv: ParsedCV, report: FitReport) -> None:
    edited = apply_fit_overrides(
        report, cv, [override("must-3", "met", ["skill-5", "skill-5"], note="K8s via Docker")]
    )

    m = edited.matches[2]
    assert (m.verdict, m.evidence_refs, m.source) == ("met", ["skill-5"], "human")
    assert m.rationale == "[Reviewer] K8s via Docker"
    assert (edited.overall_score, edited.must_have_score) == (100, 100)
    assert report.matches[2].verdict == "not_met"  # original untouched


def test_override_can_lower_a_verdict(cv: ParsedCV, report: FitReport) -> None:
    edited = apply_fit_overrides(report, cv, [override("must-1", "not_met", [], note="Too junior")])
    assert edited.matches[0].verdict == "not_met"
    assert edited.overall_score == 43  # (0+2+0+1)/7


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (override("must-99", "met", ["exp-1"]), "unknown requirement 'must-99'"),
        (override("must-3", "met", ["k8s-cert"]), "unknown CV references ['k8s-cert']"),
        (override("must-3", "met", []), "'met' needs at least one CV reference"),
        (override("must-3", "partial", []), "'partial' needs at least one CV reference"),
    ],
)
def test_invalid_overrides_rejected(
    cv: ParsedCV, report: FitReport, bad: MatchOverride, message: str
) -> None:
    """Humans can cite evidence the analyst missed, never experience the CV lacks."""
    with pytest.raises(
        ReviewValidationError, match=message.replace("[", r"\[").replace("]", r"\]")
    ):
        apply_fit_overrides(report, cv, [bad])


def test_all_errors_reported_together(cv: ParsedCV, report: FitReport) -> None:
    with pytest.raises(ReviewValidationError) as info:
        apply_fit_overrides(
            report, cv, [override("must-99", "met", []), override("must-3", "met", ["nope"])]
        )
    assert "must-99" in str(info.value) and "nope" in str(info.value)
