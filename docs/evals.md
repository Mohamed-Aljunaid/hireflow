# HireFlow evals

## What is measured

| Metric | How | Why |
|---|---|---|
| **Fabrication rate** (key metric) | Share of final tailored bullets and cover-letter paragraphs that an **independent judge** finds unsupported. The judge reads the *raw* CV text and the job posting, not the pipeline's parsed IDs. Also, in code: every number in a unit must appear in the CV or the posting. A unit the judge skips counts as fabricated. | It checks what the user would actually send, after the pipeline's own claim checker. |
| Job-parse field accuracy | title, company (loose containment), seniority, remote policy (exact), expected keywords present | Everything downstream depends on the parsed job. |
| Fit ordering | Within each job, the strong candidate must score strictly above medium, and medium above weak (ties count as wrong) | Absolute scores are arbitrary; their ranking shouldn't be. |
| Keyword coverage | Share of the job's keywords **that the CV genuinely supports** that appear in the tailored bullets | It rewards using the job's vocabulary without rewarding fabrication. |

## Dataset

`evals/dataset/`: 6 synthetic CVs and 4 job postings (Python backend, data analyst, React frontend, SRE), giving **12 pairs**, a strong, a medium and a weak candidate per job. `cases.json` holds the expected job fields and, per pair, the keywords the CV actually supports. Weak pairs are included on purpose, because they're where the pressure to pad is highest. A test checks the dataset's consistency (files exist, supported keywords appear in both the CV and the job, one candidate of each strength per job).

## Running

From the repo root:

```bash
# Free: canned LLM, proves the harness end to end (metrics are meaningless).
uv run --project backend python -m evals.run --mock

# Real model (ANTHROPIC_MODEL from .env). Costs money: see below.
uv run --project backend python -m evals.run
uv run --project backend python -m evals.run --cases backend-strong sre-weak   # subset

# Harness tests
uv run --project backend pytest evals
```

Each case runs the real graph with both gates auto-approved. Reports go to `evals/results/<UTC stamp>.{json,md}`. Mock reports (`*-mock.*`) are gitignored, while real reports are meant to be committed. Exit code: `0` ok, `1` fabrication rate above `--max-fabrication-rate`, `2` a case errored.

**Cost (rough estimate, not measured):** about 10 calls per case (CV parse, job parse, research, fit, tailor, check, write, check, judge, plus any rewrites) at `high` effort, so roughly 30k input and 30k output tokens per case. For 12 cases on Claude Opus 5.5 ($4 / $20 per MTok) that's about **$10 per full run**, plausibly anywhere from $5 to $15. Every report records the actual token usage.

## Threshold

`--max-fabrication-rate` defaults to **2%** of units. This is a proposal, **not yet agreed**. With 12 cases × about 7 units, 2% allows one or two flagged units per run.

## Results

| Date | Mode | Model | Fabrication | Job fields | Fit ordering | Keywords |
|---|---|---|---|---|---|---|
| 2026-11-16 | mock | MockLLMClient | 40.5% (34/84)¹ | 25.0% | 0/12 | 29.4% |

¹ Expected: the canned output describes a different candidate (Jordan Rivera), so the judge's number check flags its "2M", "40%" and "300+" on these CVs. That shows the harness catches mismatches; it says nothing about the model.

**No real-model run yet.** It needs an Anthropic API key and approval of the cost above.
