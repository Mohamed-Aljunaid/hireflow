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
    with pytest.raises(ValidationError, match="at least one edit"):
        ReviewDecision(action="edit")


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_overrides_only_with_edit(action: str) -> None:
    with pytest.raises(ValidationError, match="cannot carry edits"):
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


@pytest.mark.parametrize("action", ["regenerated", "approved", ""])
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


# ---------- content_review: apply_text_edits ----------


def content():
    from app.agents.schemas.content import (
        CoverLetter,
        CoverLetterParagraph,
        TailoredBullet,
        TailoredBullets,
    )

    tailored = TailoredBullets(
        bullets=[
            TailoredBullet(id="tb-1", text="a", source_cv_refs=["exp-1.b1"]),
            TailoredBullet(id="tb-2", text="b", source_cv_refs=["exp-1.b2"]),
        ]
    )
    letter = CoverLetter(
        salutation="Hi,",
        paragraphs=[CoverLetterParagraph(id="p-1", text="c", source_cv_refs=["exp-1"])],
        closing="Bye",
    )
    return tailored, letter


def test_text_edits_replace_text_and_keep_citations() -> None:
    from app.agents.review import apply_text_edits
    from app.agents.schemas.review import TextEdit

    tailored, letter = content()
    new_t, new_l = apply_text_edits(
        tailored, letter, [TextEdit(id="tb-2", text="  B!  "), TextEdit(id="p-1", text="C")]
    )

    assert [(b.text, b.author) for b in new_t.bullets] == [("a", "model"), ("B!", "human")]
    assert new_t.bullets[1].source_cv_refs == ["exp-1.b2"]
    assert (new_l.paragraphs[0].text, new_l.paragraphs[0].author) == ("C", "human")
    assert tailored.bullets[1].text == "b"  # originals untouched


def test_text_edit_unknown_id_rejected() -> None:
    from app.agents.review import apply_text_edits
    from app.agents.schemas.review import TextEdit

    tailored, letter = content()
    with pytest.raises(ReviewValidationError, match="tb-3"):
        apply_text_edits(tailored, letter, [TextEdit(id="tb-3", text="x")])


def test_text_edits_need_edit_action_and_unique_ids() -> None:
    with pytest.raises(ValidationError, match="cannot carry edits"):
        ReviewDecision(action="approve", text_edits=[{"id": "tb-1", "text": "x"}])
    with pytest.raises(ValidationError, match="at most once"):
        ReviewDecision(
            action="edit",
            text_edits=[{"id": "tb-1", "text": "x"}, {"id": "tb-1", "text": "y"}],
        )
    with pytest.raises(ValidationError):
        ReviewDecision(action="edit", text_edits=[{"id": "tb-1", "text": ""}])
