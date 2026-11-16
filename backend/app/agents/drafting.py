"""Bullet Tailor and Cover-letter Writer. Code assigns IDs and normalises citations;
the claim checker (claim_checker.py) decides whether the content stands."""

from collections.abc import Sequence

from app.agents.prompts import TAILOR_SYSTEM, WRITER_SYSTEM
from app.agents.schemas.content import (
    CoverLetter,
    CoverLetterDraft,
    CoverLetterParagraph,
    TailoredBullet,
    TailoredBullets,
    TailoringDraft,
)
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.fit import FitReport
from app.agents.schemas.job import JobPosting
from app.agents.schemas.research import CompanyBrief
from app.core.config import Effort
from app.core.llm import LLMClient


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _fit_lines(fit: FitReport) -> str:
    return "\n".join(f"[{m.requirement_id}] {m.verdict}: {m.requirement_text}" for m in fit.matches)


def _feedback_block(check_feedback: Sequence[str], reviewer_feedback: str | None) -> str:
    parts = []
    if check_feedback:
        parts.append(
            "<claim_check_failures>\nYour previous draft had unsupported content. Fix "
            "each item by staying within its cited sources, or drop it:\n"
            + "\n".join(check_feedback)
            + "\n</claim_check_failures>"
        )
    if reviewer_feedback:
        parts.append(f"<reviewer_feedback>\n{reviewer_feedback}\n</reviewer_feedback>")
    return "\n\n".join(parts)


async def tailor_bullets(
    cv: ParsedCV,
    job: JobPosting,
    fit: FitReport,
    llm: LLMClient,
    *,
    check_feedback: Sequence[str] = (),
    reviewer_feedback: str | None = None,
    effort: Effort | None = None,
) -> TailoredBullets:
    user = "\n\n".join(
        part
        for part in (
            f"<job>\n{job.render_with_ids()}\n</job>",
            f"<fit>\n{_fit_lines(fit)}\n</fit>",
            f"<cv>\n{cv.render_with_ids()}\n</cv>",
            _feedback_block(check_feedback, reviewer_feedback),
        )
        if part
    )
    draft = await llm.structured(
        system=TAILOR_SYSTEM, user=user, output_model=TailoringDraft, effort=effort
    )
    requirement_ids = {r.id for r in job.requirements}
    return TailoredBullets(
        bullets=[
            TailoredBullet(
                id=f"tb-{i}",
                text=b.text.strip(),
                source_cv_refs=_dedupe(b.source_cv_refs),
                requirement_ids=[r for r in _dedupe(b.requirement_ids) if r in requirement_ids],
            )
            for i, b in enumerate(draft.bullets, 1)
        ]
    )


async def write_cover_letter(
    cv: ParsedCV,
    job: JobPosting,
    fit: FitReport,
    bullets: TailoredBullets,
    brief: CompanyBrief,
    llm: LLMClient,
    *,
    check_feedback: Sequence[str] = (),
    reviewer_feedback: str | None = None,
    effort: Effort | None = None,
) -> CoverLetter:
    user = "\n\n".join(
        part
        for part in (
            f"<job>\n{job.render_with_ids()}\n</job>",
            f"<fit>\n{_fit_lines(fit)}\n</fit>",
            "<tailored_bullets>\n"
            + "\n".join(f"- {b.text}" for b in bullets.bullets)
            + "\n</tailored_bullets>",
            f"<cv>\n{cv.render_with_ids()}\n</cv>",
            f"<company_brief>\n{brief.render_with_ids()}\n</company_brief>",
            _feedback_block(check_feedback, reviewer_feedback),
        )
        if part
    )
    draft = await llm.structured(
        system=WRITER_SYSTEM, user=user, output_model=CoverLetterDraft, effort=effort
    )
    return CoverLetter(
        salutation=draft.salutation.strip(),
        paragraphs=[
            CoverLetterParagraph(
                id=f"p-{i}",
                text=p.text.strip(),
                source_cv_refs=_dedupe(p.source_cv_refs),
                company_fact_refs=_dedupe(p.company_fact_refs),
            )
            for i, p in enumerate(draft.paragraphs, 1)
        ],
        closing=draft.closing.strip(),
    )
