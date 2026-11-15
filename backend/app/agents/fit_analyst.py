"""Fit Analyst: CV + job posting -> FitReport.

The LLM only judges. Code enforces the rules: every cited CV ID must exist, a "met" or
"partial" verdict with no surviving evidence is downgraded to "not_met", every
requirement gets exactly one match, and the score is computed from the verdicts.
"""

from app.agents.prompts import FIT_ANALYST_SYSTEM
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import (
    FitAssessment,
    FitReport,
    GapClaim,
    RequirementMatch,
    StrengthClaim,
    Verdict,
)
from app.agents.schemas.job import JobPosting, Requirement
from app.core.config import Effort
from app.core.llm import LLMClient

VERDICT_POINTS: dict[Verdict, float] = {"met": 1.0, "partial": 0.5, "not_met": 0.0}
IMPORTANCE_WEIGHT = {"must": 2.0, "nice": 1.0}
NOT_ASSESSED = "Not assessed by the analyst; treated as not met."
DOWNGRADED = "[Downgraded: no valid CV evidence cited] "


async def analyse_fit(
    cv: ParsedCV, job: JobPosting, llm: LLMClient, *, effort: Effort | None = None
) -> FitReport:
    user = (
        f"<job_requirements>\n{job.render_with_ids()}\n</job_requirements>\n\n"
        f"<cv>\n{cv.render_with_ids()}\n</cv>"
    )
    assessment = await llm.structured(
        system=FIT_ANALYST_SYSTEM, user=user, output_model=FitAssessment, effort=effort
    )
    return build_fit_report(assessment, job=job, cv=cv)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def score_matches(matches: list[RequirementMatch], importance: str | None = None) -> int | None:
    selected = [m for m in matches if importance is None or m.importance == importance]
    if not selected:
        return None
    weights = [IMPORTANCE_WEIGHT[m.importance] for m in selected]
    points = [VERDICT_POINTS[m.verdict] * w for m, w in zip(selected, weights, strict=True)]
    return round(100 * sum(points) / sum(weights))


def build_fit_report(assessment: FitAssessment, *, job: JobPosting, cv: ParsedCV) -> FitReport:
    valid_refs = set(cv.evidence_index())
    requirements: dict[str, Requirement] = {r.id: r for r in job.requirements}
    warnings: list[str] = []

    by_requirement: dict[str, RequirementMatch] = {}
    for j in assessment.judgements:
        req = requirements.get(j.requirement_id)
        if req is None:
            warnings.append(f"Ignored judgement for unknown requirement '{j.requirement_id}'.")
            continue
        if req.id in by_requirement:
            warnings.append(f"Ignored duplicate judgement for '{req.id}'.")
            continue

        refs = _dedupe(j.evidence_refs)
        invalid = [r for r in refs if r not in valid_refs]
        if invalid:
            warnings.append(f"{req.id}: dropped unknown CV references {invalid}.")
        refs = [r for r in refs if r in valid_refs]

        verdict, rationale = j.verdict, j.rationale
        if verdict != "not_met" and not refs:
            warnings.append(f"{req.id}: '{verdict}' had no valid evidence; set to not_met.")
            verdict, rationale = "not_met", DOWNGRADED + rationale

        by_requirement[req.id] = RequirementMatch(
            requirement_id=req.id,
            requirement_text=req.text,
            importance=req.importance,
            verdict=verdict,
            evidence_refs=refs,
            rationale=rationale,
        )

    matches: list[RequirementMatch] = []
    for req in job.requirements:  # job order, exactly one match each
        match = by_requirement.get(req.id)
        if match is None:
            warnings.append(f"{req.id}: not assessed; treated as not_met.")
            match = RequirementMatch(
                requirement_id=req.id,
                requirement_text=req.text,
                importance=req.importance,
                verdict="not_met",
                evidence_refs=[],
                rationale=NOT_ASSESSED,
            )
        matches.append(match)

    strengths: list[StrengthClaim] = []
    for s in assessment.strengths:
        refs = [r for r in _dedupe(s.evidence_refs) if r in valid_refs]
        if not refs:
            warnings.append(f"Dropped strength without valid evidence: {s.text!r}.")
            continue
        strengths.append(StrengthClaim(text=s.text, evidence_refs=refs))

    gaps = [
        GapClaim(
            text=g.text,
            requirement_ids=[r for r in _dedupe(g.requirement_ids) if r in requirements],
        )
        for g in assessment.gaps
    ]

    return FitReport(
        overall_score=score_matches(matches),
        must_have_score=score_matches(matches, "must"),
        nice_to_have_score=score_matches(matches, "nice"),
        matches=matches,
        strengths=strengths,
        gaps=gaps,
        summary=assessment.summary,
        warnings=warnings,
    )
