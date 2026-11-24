# PLAN.md — HireFlow

Work one phase at a time. Stop when a phase's **Done when** is met. Every phase ends with tests passing (LLM mocked), ruff clean and `docs/decisions.md` updated.

---

## Phase 1 — Scaffold + CV parsing
**Goal:** a runnable skeleton and CV upload → structured CV.
- uv project in `backend/` (Python 3.12), ruff + pytest config, `.env.example`, `.gitignore`.
- `app/core/config.py` (pydantic-settings), the LLM client wrapper, logging.
- Async SQLAlchemy session, first Alembic migration (`cvs` table).
- Docker Compose: `db` (Postgres 16) + `api`.
- `POST /cvs`: upload a PDF/DOCX/TXT, extract text, have the LLM parse it into a `ParsedCV` model (contact, summary, experience[] with bullets, skills, education), store it. `GET /cvs/{id}`.
- `docs/decisions.md` started.

**Done when:** `docker compose up` brings up api + db; uploading a sample CV returns a validated `ParsedCV`; the tests for text extraction, parsing (mocked LLM), the endpoint and the DB round-trip pass; ruff is clean.

---

## Phase 2 — Job Parser + Fit Analyst
**Goal:** a structured job posting and a fit score.
- `JobPosting` model (title, company, location, must-haves, nice-to-haves, responsibilities, seniority, keywords).
- Job Parser agent: pasted text → `JobPosting`.
- Fit Analyst agent: `ParsedCV` + `JobPosting` → `FitReport` (overall score 0–100, per-requirement match with CV evidence refs, gaps, strengths).
- Endpoints: `POST /jobs`, `POST /fit` (standalone for now). Migration for the `jobs` table.

**Done when:** both agents return validated models from mocked LLM fixtures; every match in `FitReport` references real CV items (tested); the endpoints are tested; ruff is clean.

---

## Phase 3 — LangGraph wiring
**Goal:** the agents run as one graph with persisted state.
- `PipelineState` (typed) in `app/agents/state.py`.
- Graph: `parse_job → fit_analysis → END` (later phases add nodes).
- Postgres checkpointer configured; each run has a `thread_id` tied to an `applications` row.
- `POST /applications` starts a run; `GET /applications/{id}` returns state/status.

**Done when:** a run executes end to end with a mocked LLM; its state is persisted and reloadable from the checkpointer after an API restart (tested against a test Postgres); ruff is clean.

---

## Phase 4 — Human-in-the-loop
**Goal:** the pipeline pauses for approval at key steps.
- Interrupts (LangGraph `interrupt`) after fit analysis ("proceed?") and after bullet tailoring / cover letter ("approve / edit / regenerate").
- `POST /applications/{id}/resume` with an approve / reject / edit payload (`Command(resume=...)`).
- Status model: `running | awaiting_approval | completed | rejected | failed`.

**Done when:** tests cover pause → resume (approve), pause → edit → continue, and reject → stop; resuming works across process restarts; ruff is clean.

---

## Phase 5 — Researcher + Writer + claim checker
**Goal:** the full content-generation path, with honesty guaranteed.
- Researcher agent: company name → `CompanyBrief` (what they do, products, values, recent news, sources). Search provider behind an interface; mocked in tests.
- Bullet Tailor: produces `TailoredBullet[]`, each with `source_cv_refs`.
- Writer: `CoverLetter` model (paragraphs + the claims used).
- **Claim checker** node: verifies every tailored bullet and cover-letter claim against the `ParsedCV`. Unsupported claims are flagged and sent back for rewriting (bounded retries) before the human sees them.
- Graph: `parse_job → research → fit → [HITL] → tailor → claim_check → write → claim_check → [HITL] → END`.

**Done when:** a fabricated claim injected in a test is caught and removed or rewritten; the whole graph runs with mocks; ruff is clean.

---

## Phase 6 — Frontend pipeline UI
**Goal:** a usable web app.
- Vite + React + TS + Tailwind in `frontend/`, added to Docker Compose.
- Screens: upload CV → paste job → live pipeline view (step status, polling or SSE) → approval panels (fit report, bullets diff vs original, cover letter editor) → final export (copy / download).
- Typed API client generated from the OpenAPI spec, or written by hand to match it.

**Done when:** a user can complete the whole flow in the browser against the dockerized backend (LLM mockable via env flag); component tests (Vitest + Testing Library) pass; lint and typecheck are clean.

---

## Phase 7 — Evals
**Goal:** measurable quality.
- `evals/` dataset: about 10–20 CV + job pairs with expected properties.
- Metrics: job-parse field accuracy, fit-score sanity (ordering on known good/bad pairs), **fabrication rate** (claims not supported by the CV, the key metric), and keyword coverage of tailored bullets.
- Runner (`uv run python -m evals.run`) that hits the real model (opt-in, needs a key) and writes a results report to `evals/results/`.

**Done when:** the eval runner produces a report; the fabrication rate is reported and below the agreed threshold; results are summarized in `docs/`.

---

## Phase 8 — Deploy
**Goal:** a public demo.
- Production Dockerfiles (multi-stage), compose/prod config, healthchecks.
- Deploy to a host (decision recorded in `docs/decisions.md`), managed Postgres, secrets through the platform env.
- CI (GitHub Actions): ruff, tests, frontend lint/typecheck/tests, image build.
- README with architecture diagram, demo GIF and how to run locally.

**Done when:** the app is reachable at a public URL; CI is green on main; the README is complete.

---

## Phase 9 — Job search
**Goal:** find remote jobs open to a chosen country (default Saudi Arabia) and send one into the existing pipeline. No scraping, no auto-applying.
- Provider: Himalayas public API (`GET https://himalayas.app/jobs/api/search`, `q` + `country`). Free, no key, full descriptions.
- `app/services/job_search.py`: fetch, strip HTML, validate into a `JobListing` model (title, company, posting text, location scope, apply link, Himalayas link, published, expires). Fixed host, timeout, short cache; expired jobs dropped.
- `GET /jobs/search?q=&country=&page=`. Provider errors → 502, provider rate limit → 503.
- Order: country-only jobs first, then worldwide, then multi-country (those location tags are often wrong, so the UI says "check eligibility").
- `applications.apply_url` (nullable, migration 0004), so the apply link is still there at the export step.
- Frontend: a search panel on the job step. Picking a job fills the posting box for review; the pipeline itself is unchanged. Pasting still works.
- Himalayas terms: apply link used unchanged, visible link back on every listing, listings not passed to other boards.
- Not included: scoring every result with the LLM (costs per job), saved searches, alerts, a second provider.

**Done when:** searching returns normalized listings and picking one runs the existing pipeline; parsing, ordering, expiry, error mapping, the migration and the UI are tested with the provider's HTTP mocked; one live search is checked by hand; ruff, lint and typecheck are clean.
