"""Applying human review decisions. Pure functions, shared by the API (to validate
before resuming, returning 422 on bad input) and by the graph node (to apply)."""

from app.agents.fit_analyst import score_matches
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport, RequirementMatch
from app.agents.schemas.review import GATE_ACTIONS, MatchOverride, ReviewDecision


class ReviewValidationError(ValueError):
    """The decision is well-formed but does not fit the artifact under review."""


def check_action_allowed(gate: str, decision: ReviewDecision) -> None:
    allowed = GATE_ACTIONS[gate]
    if decision.action not in allowed:
        raise ReviewValidationError(
            f"action '{decision.action}' is not allowed at {gate} (allowed: {list(allowed)})"
        )


def apply_fit_overrides(
    report: FitReport, cv: ParsedCV, overrides: list[MatchOverride]
) -> FitReport:
    """Return a new report with human verdicts applied and scores recomputed.

    The Phase 2 evidence rule holds for humans too: every ref must be a real CV ID,
    and 'met'/'partial' needs at least one. Humans can point at evidence the analyst
    missed; they cannot add experience that is not on the CV.
    """
    valid_refs = set(cv.evidence_index())
    by_id = {m.requirement_id: m for m in report.matches}
    errors: list[str] = []
    for o in overrides:
        if o.requirement_id not in by_id:
            errors.append(f"unknown requirement '{o.requirement_id}'")
        if bad := [r for r in o.evidence_refs if r not in valid_refs]:
            errors.append(f"{o.requirement_id}: unknown CV references {bad}")
        if o.verdict != "not_met" and not o.evidence_refs:
            errors.append(f"{o.requirement_id}: '{o.verdict}' needs at least one CV reference")
    if errors:
        raise ReviewValidationError("; ".join(errors))

    replaced = {o.requirement_id: o for o in overrides}
    matches: list[RequirementMatch] = []
    for m in report.matches:
        o = replaced.get(m.requirement_id)
        if o is None:
            matches.append(m)
            continue
        matches.append(
            m.model_copy(
                update={
                    "verdict": o.verdict,
                    "evidence_refs": list(dict.fromkeys(o.evidence_refs)),
                    "rationale": f"[Reviewer] {o.note}",
                    "source": "human",
                }
            )
        )
    return report.model_copy(
        update={
            "matches": matches,
            "overall_score": score_matches(matches),
            "must_have_score": score_matches(matches, "must"),
            "nice_to_have_score": score_matches(matches, "nice"),
        }
    )
