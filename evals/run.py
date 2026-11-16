"""Run the HireFlow eval: every case through the real pipeline, both gates auto-approved,
then an independent fabrication judge and the metrics. Writes evals/results/<stamp>.{json,md}.

    uv run --project backend python -m evals.run --mock            # free, proves the harness
    uv run --project backend python -m evals.run                    # real model (costs money)
    uv run --project backend python -m evals.run --cases backend-strong sre-weak

Exit code: 0 ok, 1 fabrication rate above --max-fabrication-rate, 2 a case errored.
In --mock mode the threshold is reported but not enforced (the canned LLM output does not
match the dataset's CVs, so the numbers mean nothing).
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.graph import build_graph
from app.core.config import Settings, get_settings
from app.core.llm import AnthropicLLMClient, LLMClient
from app.core.mock_llm import UNIT_ID, MockLLMClient
from app.services.cv_parser import parse_cv
from app.services.pipeline_runner import status_from_snapshot, thread_config
from evals import judge as judge_mod
from evals.metrics import fit_ordering, job_field_accuracy, keyword_coverage

EVALS_DIR = Path(__file__).resolve().parent
DATASET = EVALS_DIR / "dataset"
DEFAULT_MAX_FABRICATION_RATE = 0.02  # proposed; see docs/evals.md


class EvalMockLLM(MockLLMClient):
    """The app's mock LLM, plus a judge that finds nothing (for harness runs)."""

    async def structured[T: BaseModel](
        self, *, system, user, output_model: type[T], effort=None
    ) -> T:
        if output_model is judge_mod.FabricationJudgment:
            ids = [line.split("]")[0][1:] for line in user.splitlines() if UNIT_ID.match(line)]
            return output_model(units=[judge_mod.UnitJudgment(unit_id=i) for i in ids])
        return await super().structured(
            system=system, user=user, output_model=output_model, effort=effort
        )


def load_dataset() -> tuple[dict, list[dict]]:
    spec = json.loads((DATASET / "cases.json").read_text(encoding="utf-8"))
    return spec["jobs"], spec["cases"]


async def run_case(case: dict, expected_job: dict, llm: LLMClient, settings: Settings) -> dict:
    cv_text = (DATASET / "cvs" / f"{case['cv']}.txt").read_text(encoding="utf-8")
    job_text = (DATASET / "jobs" / f"{case['job']}.txt").read_text(encoding="utf-8")
    result: dict[str, Any] = {"id": case["id"], "job": case["job"], "cv": case["cv"],
                              "fit": case["fit"]}  # fmt: skip
    try:
        cv = await parse_cv(cv_text, llm)
        graph = build_graph(llm, settings).compile(checkpointer=InMemorySaver())
        config = thread_config(case["id"])
        await graph.ainvoke(
            {"application_id": case["id"], "cv": cv.model_dump(mode="json"), "job_text": job_text},
            config,
        )
        # Auto-approve both gates: weak fits are included on purpose (most tempting to pad).
        for _ in range(2):
            await graph.ainvoke(Command(resume={"action": "approve"}), config)
        snapshot = await graph.aget_state(config)
        status = status_from_snapshot(snapshot)
        if status != "completed":
            raise RuntimeError(f"pipeline ended in status {status!r}")
        state = snapshot.values

        bullets = {b["id"]: b["text"] for b in state["tailored"]["bullets"]}
        paragraphs = {p["id"]: p["text"] for p in state["cover_letter"]["paragraphs"]}
        verdicts = await judge_mod.judge_units(
            bullets | paragraphs, cv_text, job_text, llm, effort=settings.anthropic_analysis_effort
        )
        hits, possible = keyword_coverage(list(bullets.values()), case["supported_keywords"])
        result |= {
            "overall_score": state["fit_report"]["overall_score"],
            "job_fields": job_field_accuracy(state["job"], expected_job),
            "units": len(verdicts),
            "fabricated": {uid: claims for uid, claims in verdicts.items() if claims},
            "keyword_hits": hits,
            "keyword_possible": possible,
            "pipeline_warnings": state["tailored"]["warnings"] + state["cover_letter"]["warnings"],
            "bullets": list(bullets.values()),
        }
    except Exception as exc:  # one bad case must not sink the run
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def summarise(results: list[dict], max_rate: float, mock: bool, model: str, usage: dict) -> dict:
    ok = [r for r in results if "error" not in r]
    units = sum(r["units"] for r in ok)
    fabricated = sum(len(r["fabricated"]) for r in ok)
    field_checks = [v for r in ok for v in r["job_fields"].values()]
    correct, pairs, wrong_pairs = fit_ordering(ok)
    kw_hits = sum(r["keyword_hits"] for r in ok)
    kw_possible = sum(r["keyword_possible"] for r in ok)
    rate = fabricated / units if units else None
    return {
        "mode": "mock" if mock else "real",
        "model": "MockLLMClient" if mock else model,
        "cases": len(results),
        "errors": len(results) - len(ok),
        "fabrication_rate": rate,
        "fabricated_units": fabricated,
        "units": units,
        "max_fabrication_rate": max_rate,
        "fabrication_ok": rate is not None and rate <= max_rate,
        "job_field_accuracy": sum(field_checks) / len(field_checks) if field_checks else None,
        "fit_ordering": correct / pairs if pairs else None,
        "fit_ordering_pairs": f"{correct}/{pairs}",
        "fit_ordering_wrong": wrong_pairs,
        "keyword_coverage": kw_hits / kw_possible if kw_possible else None,
        "usage": usage,
    }


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def markdown(summary: dict, results: list[dict], stamp: str) -> str:
    lines = [f"# HireFlow eval — {stamp}", ""]
    if summary["mode"] == "mock":
        lines += ["> **MOCK RUN** — canned LLM output; metrics only prove the harness works.", ""]
    verdict = "PASS" if summary["fabrication_ok"] else "FAIL"
    lines += [
        f"- Model: `{summary['model']}`, cases: {summary['cases']}, errors: {summary['errors']}",
        f"- **Fabrication rate: {pct(summary['fabrication_rate'])}** "
        f"({summary['fabricated_units']}/{summary['units']} units) — threshold "
        f"{pct(summary['max_fabrication_rate'])}: **{verdict}**",
        f"- Job-parse field accuracy: {pct(summary['job_field_accuracy'])}",
        f"- Fit ordering: {pct(summary['fit_ordering'])} ({summary['fit_ordering_pairs']} pairs)",
        f"- Keyword coverage (CV-supported only): {pct(summary['keyword_coverage'])}",
        f"- Usage: {summary['usage']}",
        "",
        "| case | fit | score | job fields | keywords | fabricated/units | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fields = r.get("job_fields", {})
        lines.append(
            f"| {r['id']} | {r['fit']} | {r.get('overall_score', '')} "
            f"| {sum(fields.values())}/{len(fields)} "
            f"| {r.get('keyword_hits', '')}/{r.get('keyword_possible', '')} "
            f"| {len(r.get('fabricated', {}))}/{r.get('units', '')} | {r.get('error', '')} |"
        )
    if summary["fit_ordering_wrong"]:
        lines += [
            "",
            "## Fit ordering mistakes",
            *(f"- {w}" for w in summary["fit_ordering_wrong"]),
        ]
    flagged = [(r["id"], uid, c) for r in results for uid, c in r.get("fabricated", {}).items()]
    if flagged:
        lines += ["", "## Fabricated units"]
        lines += [f"- {cid} [{uid}]: {'; '.join(claims)}" for cid, uid, claims in flagged]
    return "\n".join(lines) + "\n"


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mock", action="store_true", help="canned LLM, no key, no cost")
    parser.add_argument("--cases", nargs="*", help="case ids to run (default: all)")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-fabrication-rate", type=float, default=DEFAULT_MAX_FABRICATION_RATE)
    parser.add_argument("--out", type=Path, default=EVALS_DIR / "results")
    args = parser.parse_args(argv)

    jobs, cases = load_dataset()
    if args.cases:
        unknown = set(args.cases) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in args.cases]

    if args.mock:
        settings = Settings(_env_file=None, llm_mock=True)
        llm: LLMClient = EvalMockLLM()
    else:
        settings = get_settings()
        llm = AnthropicLLMClient(settings)

    gate = asyncio.Semaphore(args.concurrency)

    async def bounded(case: dict) -> dict:
        async with gate:
            print(f"  running {case['id']}…", flush=True)
            return await run_case(case, jobs[case["job"]], llm, settings)

    results = await asyncio.gather(*(bounded(c) for c in cases))
    usage = getattr(llm, "usage", {})
    summary = summarise(
        results, args.max_fabrication_rate, args.mock, settings.anthropic_model, usage
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ("-mock" if args.mock else "")
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"summary": summary, "results": results}
    (args.out / f"{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = markdown(summary, results, stamp)
    (args.out / f"{stamp}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"Report: {args.out / stamp}.{{json,md}}")

    if summary["errors"]:
        return 2
    if not args.mock and not summary["fabrication_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
