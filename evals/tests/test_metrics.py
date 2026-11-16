import pytest

from evals.metrics import fit_ordering, job_field_accuracy, keyword_coverage

EXPECTED = {
    "title": "Senior Backend Engineer",
    "company": "Harbor Analytics",
    "seniority": "senior",
    "remote_policy": "remote",
    "keywords": ["Python", "PostgreSQL"],
}


def test_job_fields_all_correct_with_loose_title_and_keyword_matching() -> None:
    parsed = {
        "title": "Senior Backend Engineer (Python)",
        "company": "Harbor Analytics GmbH",
        "seniority": "senior",
        "remote_policy": "remote",
        "keywords": ["python", "PostgreSQL 16", "Kubernetes"],
    }
    assert all(job_field_accuracy(parsed, EXPECTED).values())


def test_job_fields_report_each_mistake() -> None:
    parsed = {"title": "Data Analyst", "company": None, "seniority": "mid",
              "remote_policy": "hybrid", "keywords": ["Python"]}  # fmt: skip
    assert job_field_accuracy(parsed, EXPECTED) == {
        "title": False,
        "company": False,
        "seniority": False,
        "remote_policy": False,
        "keywords": False,  # PostgreSQL missing
    }


def r(id_: str, job: str, fit: str, score: int | None) -> dict:
    return {"id": id_, "job": job, "fit": fit, "overall_score": score}


def test_fit_ordering_counts_pairs_within_each_job() -> None:
    results = [
        r("a-strong", "a", "strong", 90), r("a-medium", "a", "medium", 60),
        r("a-weak", "a", "weak", 70),  # beats medium: one wrong pair
        r("b-strong", "b", "strong", 80), r("b-weak", "b", "weak", 10),
    ]  # fmt: skip
    correct, total, wrong = fit_ordering(results)
    assert (correct, total) == (3, 4)
    assert wrong == ["a: a-medium (60) should beat a-weak (70)"]


def test_fit_ordering_ties_count_as_wrong_and_missing_scores_are_skipped() -> None:
    results = [r("s", "a", "strong", 50), r("w", "a", "weak", 50), r("x", "a", "medium", None)]
    assert fit_ordering(results)[:2] == (0, 1)


@pytest.mark.parametrize(
    ("bullets", "supported", "expected"),
    [
        (["Built FastAPI services on Kubernetes."], ["FastAPI", "Kubernetes", "Celery"], (2, 3)),
        (["Wrote A/B testing analyses."], ["A/B testing"], (1, 1)),
        (["Anything"], [], (0, 0)),
    ],
)
def test_keyword_coverage(bullets: list[str], supported: list[str], expected: tuple) -> None:
    assert keyword_coverage(bullets, supported) == expected
