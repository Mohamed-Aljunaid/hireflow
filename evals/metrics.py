"""Pure metric functions (no LLM)."""

import re
from itertools import combinations

FIT_RANK = {"strong": 3, "medium": 2, "weak": 1}


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def job_field_accuracy(parsed: dict, expected: dict) -> dict[str, bool]:
    """Per-field correctness of the parsed job posting.

    title/company: either normalised string contains the other ("Senior Backend Engineer
    (Python)" matches "Senior Backend Engineer"). seniority/remote_policy: exact.
    keywords: every expected keyword appears among the parsed keywords.
    """

    def contains(a: str | None, b: str | None) -> bool:
        a, b = _norm(a), _norm(b)
        return bool(a and b) and (a in b or b in a)

    parsed_keywords = {_norm(k) for k in parsed.get("keywords", [])}
    return {
        "title": contains(parsed.get("title"), expected["title"]),
        "company": contains(parsed.get("company"), expected["company"]),
        "seniority": parsed.get("seniority") == expected["seniority"],
        "remote_policy": parsed.get("remote_policy") == expected["remote_policy"],
        "keywords": all(
            any(_norm(k) in p or p in _norm(k) for p in parsed_keywords if p)
            for k in expected["keywords"]
        ),
    }


def fit_ordering(results: list[dict]) -> tuple[int, int, list[str]]:
    """Within each job, a better-labelled fit must score strictly higher.

    Returns (correct pairs, total pairs, descriptions of wrong pairs).
    """
    by_job: dict[str, list[dict]] = {}
    for r in results:
        if r.get("overall_score") is not None:
            by_job.setdefault(r["job"], []).append(r)
    correct = total = 0
    wrong: list[str] = []
    for job, rs in by_job.items():
        for a, b in combinations(rs, 2):
            if FIT_RANK[a["fit"]] == FIT_RANK[b["fit"]]:
                continue
            hi, lo = (a, b) if FIT_RANK[a["fit"]] > FIT_RANK[b["fit"]] else (b, a)
            total += 1
            if hi["overall_score"] > lo["overall_score"]:
                correct += 1
            else:
                wrong.append(
                    f"{job}: {hi['id']} ({hi['overall_score']}) should beat "
                    f"{lo['id']} ({lo['overall_score']})"
                )
    return correct, total, wrong


def keyword_coverage(bullets: list[str], supported_keywords: list[str]) -> tuple[int, int]:
    """How many keywords the CV genuinely supports made it into the tailored bullets.

    Only CV-supported keywords count, so the metric never rewards fabrication.
    """
    text = _norm(" ".join(bullets))
    hits = sum(1 for k in supported_keywords if _norm(k) in text)
    return hits, len(supported_keywords)
