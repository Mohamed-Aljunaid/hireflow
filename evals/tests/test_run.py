import json
from pathlib import Path

import pytest

from evals import run
from evals.metrics import FIT_RANK


def test_dataset_is_consistent() -> None:
    jobs, cases = run.load_dataset()
    assert 10 <= len(cases) <= 20
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["job"] in jobs
        assert (run.DATASET / "cvs" / f"{c['cv']}.txt").exists()
        assert (run.DATASET / "jobs" / f"{c['job']}.txt").exists()
        assert c["fit"] in FIT_RANK
        # Supported keywords must be on the CV and asked for by the job.
        cv_text = (run.DATASET / "cvs" / f"{c['cv']}.txt").read_text(encoding="utf-8").lower()
        for k in c["supported_keywords"]:
            assert k.lower() in cv_text, (c["id"], k)
            assert k in jobs[c["job"]]["keywords"], (c["id"], k)
    # Every job has one strong, one medium and one weak candidate.
    for job in jobs:
        assert sorted(c["fit"] for c in cases if c["job"] == job) == ["medium", "strong", "weak"]


async def test_mock_run_writes_reports(tmp_path: Path) -> None:
    code = await run.main(
        ["--mock", "--cases", "backend-strong", "sre-weak", "--out", str(tmp_path)]
    )

    assert code == 0  # mock mode never enforces the threshold
    [json_file] = tmp_path.glob("*-mock.json")
    report = json.loads(json_file.read_text(encoding="utf-8"))
    summary = report["summary"]
    assert summary["mode"] == "mock"
    assert summary["cases"] == 2 and summary["errors"] == 0
    assert summary["units"] == 14  # 4 bullets + 3 paragraphs per case
    # The canned output is about a different candidate: its numbers are caught.
    assert summary["fabricated_units"] > 0
    md = json_file.with_suffix(".md").read_text(encoding="utf-8")
    assert "MOCK RUN" in md and "| backend-strong |" in md


async def test_unknown_case_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        await run.main(["--mock", "--cases", "nope", "--out", str(tmp_path)])


def test_summary_threshold() -> None:
    results = [
        {"id": "a", "job": "j", "fit": "strong", "overall_score": 80, "units": 50,
         "fabricated": {"tb-1": ["x"]}, "job_fields": {"title": True},
         "keyword_hits": 1, "keyword_possible": 2},
    ]  # fmt: skip
    s = run.summarise(results, 0.02, mock=False, model="m", usage={})
    assert (s["fabrication_rate"], s["fabrication_ok"]) == (0.02, True)
    assert run.summarise(results, 0.01, mock=False, model="m", usage={})["fabrication_ok"] is False
