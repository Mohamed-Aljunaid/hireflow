"""Claim checker: verifies tailored bullets and cover-letter paragraphs against their
cited sources (CV items, company facts).

Two layers. Code first: cited IDs must exist, bullets must cite the CV, and every number
in a claim must appear in its cited sources. Then the LLM judges whether the cited text
supports each claim. A unit the LLM skips counts as unsupported.
"""

import re
from dataclasses import dataclass

from app.agents.prompts import CLAIM_CHECKER_SYSTEM
from app.agents.schemas.content import ClaimCheck, CoverLetter, TailoredBullets
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.research import CompanyBrief
from app.core.config import Effort
from app.core.llm import LLMClient

Problems = dict[str, list[str]]

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Unit:
    id: str
    text: str
    cv_refs: list[str]
    fact_refs: list[str]
    needs_cv_ref: bool


def bullet_units(tailored: TailoredBullets) -> list[Unit]:
    return [Unit(b.id, b.text, b.source_cv_refs, [], True) for b in tailored.bullets]


def paragraph_units(letter: CoverLetter) -> list[Unit]:
    return [
        Unit(p.id, p.text, p.source_cv_refs, p.company_fact_refs, False) for p in letter.paragraphs
    ]


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def deterministic_problems(
    units: list[Unit], cv_index: dict[str, str], fact_index: dict[str, str]
) -> Problems:
    problems: Problems = {}
    for u in units:
        found: list[str] = []
        if bad := [r for r in u.cv_refs if r not in cv_index]:
            found.append(f"cites unknown CV items {bad}")
        if bad := [r for r in u.fact_refs if r not in fact_index]:
            found.append(f"cites unknown company facts {bad}")
        if u.needs_cv_ref and not u.cv_refs:
            found.append("cites no CV item")
        cited = " ".join(
            [cv_index.get(r, "") for r in u.cv_refs] + [fact_index.get(r, "") for r in u.fact_refs]
        )
        if missing := sorted(_numbers(u.text) - _numbers(cited)):
            found.append(f"numbers not in the cited sources: {missing}")
        if found:
            problems[u.id] = found
    return problems


def render_units(units: list[Unit], cv_index: dict[str, str], fact_index: dict[str, str]) -> str:
    out = []
    for u in units:
        lines = [f"[{u.id}] {u.text}", "  Cited sources:"]
        lines += [f"    [{r}] {cv_index.get(r, '(unknown)')}" for r in u.cv_refs]
        lines += [f"    [{r}] {fact_index.get(r, '(unknown)')}" for r in u.fact_refs]
        if not u.cv_refs and not u.fact_refs:
            lines.append("    (none)")
        out.append("\n".join(lines))
    return "\n\n".join(out)


async def check_claims(
    units: list[Unit],
    cv: ParsedCV,
    brief: CompanyBrief | None,
    llm: LLMClient,
    *,
    effort: Effort | None = None,
) -> Problems:
    """Return {unit_id: [problem, ...]} for every unsupported unit (empty = all good)."""
    if not units:
        return {}
    cv_index = cv.evidence_index()
    fact_index = brief.fact_index() if brief else {}
    problems = deterministic_problems(units, cv_index, fact_index)

    result = await llm.structured(
        system=CLAIM_CHECKER_SYSTEM,
        user=render_units(units, cv_index, fact_index),
        output_model=ClaimCheck,
        effort=effort,
    )
    ids = {u.id for u in units}
    judged = set()
    for f in result.findings:
        if f.unit_id not in ids:
            continue
        judged.add(f.unit_id)
        if not f.supported:
            problems.setdefault(f.unit_id, []).extend(
                f.problems or ["not supported by the cited sources"]
            )
    for unit_id in ids - judged:
        problems.setdefault(unit_id, []).append("not verified by the claim checker")
    return problems


def feedback_lines(units: list[Unit], problems: Problems) -> list[str]:
    """Problems as rewrite instructions for the drafting agent."""
    return [
        f'[{u.id}] "{u.text}" -> {"; ".join(problems[u.id])}' for u in units if u.id in problems
    ]


def drop_bullets(tailored: TailoredBullets, problems: Problems) -> TailoredBullets:
    kept = [b for b in tailored.bullets if b.id not in problems]
    warnings = [
        f"Removed bullet {b.id} after rewrites still failed the claim check: "
        f"{'; '.join(problems[b.id])}"
        for b in tailored.bullets
        if b.id in problems
    ]
    return TailoredBullets(bullets=kept, warnings=[*tailored.warnings, *warnings])


def drop_paragraphs(letter: CoverLetter, problems: Problems) -> CoverLetter:
    kept = [p for p in letter.paragraphs if p.id not in problems]
    warnings = [
        f"Removed paragraph {p.id} after rewrites still failed the claim check: "
        f"{'; '.join(problems[p.id])}"
        for p in letter.paragraphs
        if p.id in problems
    ]
    return letter.model_copy(update={"paragraphs": kept, "warnings": [*letter.warnings, *warnings]})
