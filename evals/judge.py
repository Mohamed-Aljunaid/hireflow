"""Independent fabrication judge.

Unlike the pipeline's claim checker (which judges each unit against the CV items it
*cites*, via our own parsed IDs), the judge reads the **raw CV text** and the job posting,
with no IDs. A unit is fabricated if it states anything about the candidate the CV does
not support, or anything about the company the posting does not say. Numbers are also
checked in code: every number in a unit must appear in the CV or the posting.
"""

from pydantic import BaseModel, Field

from app.agents.claim_checker import numbers  # same rule as the pipeline's code check
from app.core.config import Effort
from app.core.llm import LLMClient

JUDGE_SYSTEM = """\
You audit job-application material for fabrication. You get the candidate's CV (raw \
text), the job posting, and numbered units: tailored CV bullets [tb-N] and cover-letter \
paragraphs [p-N].

For EVERY unit, list each unsupported claim:
- about the candidate: anything not stated in the CV, or stronger than the CV states \
(extra technologies, bigger scope, leadership, outcomes, different numbers, years of \
experience the dates don't show);
- about the company: anything the job posting does not say.

Faithful rephrasing, summarising and emphasis are fine. Politeness and motivation \
("I would welcome a conversation") are fine. Return an empty list for a clean unit. \
Be strict: when in doubt, list it.
"""


class UnitJudgment(BaseModel):
    unit_id: str
    unsupported_claims: list[str] = Field(default_factory=list)


class FabricationJudgment(BaseModel):
    units: list[UnitJudgment]


async def judge_units(
    units: dict[str, str],
    cv_text: str,
    job_text: str,
    llm: LLMClient,
    *,
    effort: Effort | None = None,
) -> dict[str, list[str]]:
    """{unit_id: [unsupported claim, ...]} for every unit; empty list = clean."""
    if not units:
        return {}
    user = (
        f"<cv>\n{cv_text}\n</cv>\n\n<job_posting>\n{job_text}\n</job_posting>\n\n<units>\n"
        + "\n".join(f"[{uid}] {text}" for uid, text in units.items())
        + "\n</units>"
    )
    judgment = await llm.structured(
        system=JUDGE_SYSTEM, user=user, output_model=FabricationJudgment, effort=effort
    )
    found = {j.unit_id: list(j.unsupported_claims) for j in judgment.units if j.unit_id in units}
    source_numbers = numbers(cv_text) | numbers(job_text)
    result: dict[str, list[str]] = {}
    for uid, text in units.items():
        claims = found.get(uid, ["not judged (judge skipped this unit)"])
        if missing := sorted(numbers(text) - source_numbers):
            claims = [*claims, f"numbers not in the CV or posting: {missing}"]
        result[uid] = claims
    return result
