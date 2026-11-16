# Decision log

Each entry: date, decision, context, alternatives, consequences.

---

## 2026-11-15 — Structured LLM output via `beta.messages.parse` + Pydantic
- **Decision:** Every LLM call goes through `app/core/llm.py::AnthropicLLMClient.structured()`, which calls `client.beta.messages.parse(output_format=<PydanticModel>)` and returns a validated instance. `stop_reason` is checked (`refusal` → `LLMRefusalError`, `max_tokens` → `LLMTruncatedError`) before the output is used.
- **Context:** CLAUDE.md requires structured outputs for anything feeding another step. The SDK's parse helper converts the model to a JSON schema (`output_config.format`) and validates the response.
- **Alternatives:** forced tool use (rejected with a 400 on Claude Opus 5.5); hand-parsing JSON from text (fragile).
- **Consequences:** Agents depend only on the `LLMClient` protocol, so tests inject `FakeLLMClient`. One test runs the real SDK against a mocked HTTP transport to catch schema or request-shape regressions without the network.

## 2026-11-15 — LLM error taxonomy and HTTP mapping
- **Decision:** The client wraps every SDK failure. `LLMUnavailableError` covers missing or rejected credentials, 429, 5xx/529 and connection errors, and maps to **503**. Plain `LLMError` covers refusals, truncation, failed validation and other 4xx responses, and maps to **502**. An unrelated `TypeError` is re-raised, not swallowed.
- **Context:** A smoke run with no API key returned a raw 500 from the SDK's credential check. A caller needs to tell "try again later" apart from "this input failed".
- **Consequences:** Nothing is stored when parsing fails. The SDK's built-in retries (2) still apply before an error surfaces.

## 2026-11-15 — Model, effort and refusal fallback come from env
- **Decision:** `ANTHROPIC_MODEL` (default `claude-opus-5-5`), `ANTHROPIC_EFFORT` (default `medium`, set explicitly) and `ANTHROPIC_REFUSAL_FALLBACK` (default on: beta `server-side-fallback-2026-07-01` with `fallbacks: "default"`).
- **Context:** CV text can trip a safety classifier by accident. The fallback reroutes a declined request instead of failing the upload. Effort `medium` is enough for extraction; later agents may override it.
- **Consequences:** The fallback uses the beta Messages endpoint. Turn it off with `ANTHROPIC_REFUSAL_FALLBACK=false`.

## 2026-11-15 — Two CV models: `CVExtraction` (LLM) → `ParsedCV` (stored, with IDs)
- **Decision:** The LLM returns `CVExtraction`, which has no IDs. Code converts it to `ParsedCV`, assigning deterministic IDs (`exp-1`, `exp-1.b1`, `proj-1.b1`).
- **Context:** Later phases cite CV evidence (`source_cv_refs`), and the claim checker needs IDs it can trust. Model-generated IDs could collide or be invented.
- **Alternatives:** have the LLM emit IDs; use content hashes (unstable when text is edited).
- **Consequences:** IDs are stable for a given parse. Re-parsing a CV can renumber them, which is fine because each application references one stored CV.

## 2026-11-15 — Text extraction: pypdf + python-docx, extension-first detection
- **Decision:** Detect the file type from the extension first and fall back to the MIME type. Parse PDFs with pypdf, DOCX with python-docx (paragraphs and tables), and TXT/MD with UTF-8 → latin-1 decoding. Extraction runs in a threadpool. Uploads are capped at `MAX_UPLOAD_BYTES` (5 MB).
- **Context:** Browsers send unreliable MIME types for .docx. Parsing is CPU-bound and synchronous.
- **Alternatives:** sending the PDF to Claude as a document block (costs more, and gives us no raw text to keep); unstructured/pdfminer (heavier).
- **Consequences:** Scanned PDFs without a text layer are rejected with a 422, and OCR is out of scope. The extracted text is stored in `cvs.raw_text` for later claim checking. Nothing is truncated before the LLM call.

## 2026-11-15 — Portable column types; SQLite for unit tests, Postgres gated
- **Decision:** `parsed` uses `JSON().with_variant(JSONB, "postgresql")`, the IDs are the generic `Uuid`, and timestamps are `DateTime(timezone=True)` set in Python. Unit and API tests run on in-memory SQLite (aiosqlite). A Postgres round-trip test runs the real migration and is enabled by `TEST_DATABASE_URL`. A migration test checks the offline Postgres DDL (JSONB, TIMESTAMPTZ, UUID) and that the models match the migrations (autogenerate diff is empty).
- **Context:** The dev machine has no Docker or Postgres yet. Tests must be fast and runnable anywhere.
- **Alternatives:** testcontainers (needs Docker); Postgres-only tests (blocked locally).
- **Consequences:** Postgres-specific behaviour is only exercised when `TEST_DATABASE_URL` is set, so CI (Phase 8) must set it.

## 2026-11-15 — Tooling: uv, everything on E:
- **Decision:** `backend/` is a uv project (`package = false`, Python pinned to 3.12). `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` point at `E:\ai-agent-portfolio\`, and pytest's `--basetemp=.pytest-tmp` keeps tmp dirs off C:. ruff selects E, F, W, I, B, UP, ASYNC, SIM, RUF. `alembic` is declared third-party for isort because the local `alembic/` migrations directory shadows it.
- **Consequences:** Docker Desktop stores images on C: by default. When it is installed, move its disk image location to E: (Settings → Resources → Advanced).

---

## 2026-11-15 — Phase 2: the fit score is computed in code, not by the LLM
- **Decision:** The Fit Analyst LLM returns one verdict per requirement (`met` / `partial` / `not_met`) with cited CV IDs. `build_fit_report()` computes the score: met = 1, partial = 0.5, not_met = 0, with must-haves weighted 2× and nice-to-haves 1×. `must_have_score` and `nice_to_have_score` are reported separately. All scores are `None` when the job lists no requirements.
- **Context:** A model-chosen number (for example "78") is not reproducible, can't be explained and drifts between runs. Verdicts can each be checked against evidence.
- **Alternatives:** an LLM-chosen 0–100 score; embedding similarity (unexplainable).
- **Consequences:** The score is transparent, and tests pin it down. The weights live in `app/agents/fit_analyst.py` and can be tuned in Phase 7 evals.

## 2026-11-15 — Evidence is enforced in code
- **Decision:** Every citable CV item has an ID. Roles, projects and bullets carry stored IDs (`exp-1`, `exp-1.b2`, `proj-1.b1`). Summary, education, skills, certifications and languages get positional IDs (`summary`, `edu-1`, `skill-3`, `cert-1`, `lang-2`) via `ParsedCV.evidence_index()`. The LLM sees the CV rendered with IDs. After the call, code:
  - drops cited IDs that don't exist;
  - downgrades `met` or `partial` to `not_met` when no valid evidence remains;
  - ignores unknown or duplicate requirement IDs, and fills unassessed requirements as `not_met`;
  - drops strengths with no valid evidence.

  Every correction is recorded in `FitReport.warnings`.
- **Context:** PLAN requires "every match references real CV items". The Phase 5 claim checker depends on the same IDs.
- **Alternatives:** retrying the LLM on invalid output (costs more and still isn't guaranteed); trusting the model.
- **Consequences:** Model mistakes make the report more conservative, never more flattering, and the warnings stay visible for evals. Positional IDs are safe only because a stored ParsedCV is immutable; any future CV editing must keep the list order or re-version the CV.

## 2026-11-15 — Job postings use the same extraction → IDs pattern
- **Decision:** `JobPostingExtraction` is the LLM output. `JobPosting` adds requirement IDs `must-N` and `nice-N`. Seniority, remote policy and requirement categories are `Literal` enums, so the structured-output schema constrains them. The posting must be 50–50,000 characters; oversized input gets a 413, and nothing is truncated.
- **Consequences:** Requirement IDs are stable per stored job and are what fit matches and gaps reference.

## 2026-11-15 — Per-call effort; LLM errors via app-wide exception handlers
- **Decision:** `LLMClient.structured(..., effort=None)` overrides the default effort for a single call. Fit analysis runs at `ANTHROPIC_ANALYSIS_EFFORT` (default `high`); extraction stays at `ANTHROPIC_EFFORT` (`medium`). `LLMUnavailableError` → 503 and `LLMError` → 502 are now registered once in `app/api/errors.py` instead of in each route.
- **Consequences:** Routes stay thin, and new LLM endpoints get correct error codes automatically.

## 2026-11-15 — `/fit` is not persisted in Phase 2
- **Decision:** `POST /fit {cv_id, job_id}` computes and returns a report without storing it.
- **Context:** In Phase 3 the fit report becomes part of the LangGraph state for an application, which is checkpointed in Postgres. A separate `fit_reports` table now would be thrown away then.
- **Consequences:** Every call to `/fit` runs the LLM again.

---

## 2026-11-15 — Phase 3: graph state holds JSON dicts, not Pydantic instances
- **Decision:** `PipelineState` is a `TypedDict` whose values are `model_dump(mode="json")` dicts. Nodes validate their inputs with the Pydantic models at the boundary.
- **Context:** The checkpointer serialises state on every step. LangGraph 4.x restricts which classes it will deserialize, and a pickled-style class reference breaks when a model is renamed or moved.
- **Alternatives:** Pydantic models in state plus a serializer allowlist (couples checkpoints to class paths).
- **Consequences:** Checkpoints can be read as plain JSON in Postgres and survive refactors. A test asserts that the state is JSON-serialisable.

## 2026-11-15 — Runs execute in the background; status on the row, state in the checkpointer
- **Decision:** `POST /applications` stores an `applications` row (`id` = LangGraph `thread_id`, status `running`) and starts the graph as an asyncio task via `PipelineRunner`, returning **202**. `GET /applications/{id}` combines the row (status, error) with `graph.aget_state()` (job, fit report, `next_steps`). Runs use `durability="sync"`, so each step's checkpoint is saved before the next step starts.
- **Context:** The Phase 6 UI needs a live pipeline view, and Phase 4 interrupts make runs pause, so a synchronous request/response wouldn't fit.
- **Alternatives:** a synchronous request (times out with several LLM calls, blocks the worker); a task queue such as Celery or arq (an extra service, not needed yet).
- **Consequences:** Runs live in the API process. A single API replica is assumed until a queue is introduced.

## 2026-11-15 — Crash recovery: resume `running` applications at startup
- **Decision:** At startup the lifespan calls `PipelineRunner.resume_incomplete()`. For each row still `running`:
  - if the checkpoint has pending nodes, the run continues with `ainvoke(None, config)`, and finished nodes are **not** re-run;
  - if there is no checkpoint yet, the run restarts from the stored inputs;
  - if the run actually finished, only the status is corrected.

  Shutdown cancels in-flight tasks and leaves them `running`, so they resume on the next start. LLM failures set `failed` with the error message; unexpected exceptions set `failed` with `internal error: <Type>`, so internals aren't leaked.
- **Testing:** The restart guarantee is tested with `AsyncSqliteSaver` on a file: process A is cancelled mid-`fit_analysis`, and process B, with fresh saver, graph and runner on the same file, resumes and calls only the fit LLM. The same scenario against real Postgres (`AsyncPostgresSaver`) is in `test_checkpointer.py` and needs `TEST_DATABASE_URL`.
- **Consequences:** A step interrupted mid-flight is re-run, so nodes must stay idempotent (they are: pure LLM calls whose results are written to state).

## 2026-11-15 — Checkpointer: AsyncPostgresSaver on a psycopg pool; in-memory fallback
- **Decision:** `open_checkpointer()` turns `DATABASE_URL` into a libpq URL and opens an `AsyncConnectionPool` with the settings the saver requires (`autocommit`, `prepare_threshold=0`, `dict_row`). It then calls `saver.setup()` on each start; setup is idempotent and owns the checkpoint tables (Alembic does not). Non-Postgres URLs get an `InMemorySaver` with a loud warning, which is for local smoke runs only.
- **Consequences:** There are two Postgres drivers: asyncpg (SQLAlchemy) and psycopg (LangGraph). On **Windows**, psycopg's async mode needs the selector event loop. Tests set it in `conftest.py`. uvicorn's `--loop` option (`auto|asyncio|uvloop`) cannot select it, so running the API natively on Windows against Postgres is unsupported; run it in Docker (Linux) as intended. Native Windows runs with a SQLite URL still work, using the in-memory checkpointer.

---

## 2026-11-15 — Phase 4: approval gates are LangGraph `interrupt()` nodes
- **Decision:** A gate is a node that calls `interrupt({"gate", "allowed_actions", "payload"})`. `POST /applications/{id}/resume` sends a `ReviewDecision` (`approve` | `edit` | `reject`, optional `feedback`), which the graph receives through `Command(resume=...)`. Every decision is appended to `state.reviews` (a list reducer). A rejection also sets `state.rejection`, and a conditional edge routes it to END.
- **Scope:** PLAN lists gates after fit analysis and after tailoring and the cover letter. The last two nodes arrive in Phase 5, so Phase 4 ships the mechanism plus the **fit_review** gate. Phase 5 adds its gates (and a `regenerate` action) by extending `GATE_ACTIONS`.
- **Consequences:** Code in a gate before `interrupt()` re-runs on resume, so it must stay side-effect free.

## 2026-11-15 — "Edit" at the fit gate = verdict overrides with real evidence
- **Decision:** An edit is a list of `MatchOverride {requirement_id, verdict, evidence_refs, note}`. `apply_fit_overrides()` applies the Phase 2 evidence rule to humans as well: refs must be real CV IDs, and `met`/`partial` needs at least one. Overridden matches are marked `source: "human"`, their rationale becomes `[Reviewer] <note>`, and the scores are recomputed.
- **Context:** A reviewer often spots evidence the analyst missed, or disagrees on a judgement call. Letting them write in experience the CV lacks would undo the no-fabrication rule for every later step.
- **Alternatives:** free-form editing of the report (unverifiable); re-running the analyst with feedback (that's `regenerate`, planned for Phase 5).
- **Consequences:** To claim experience that isn't on the CV, the user must add it to the CV first, which is the honest workflow.

## 2026-11-15 — Resume is validated up front and claimed atomically
- **Decision:** `PipelineRunner.resume()` checks the request before touching the run:
  1. a gate must be pending in the checkpoint (otherwise **409**);
  2. the action must be allowed at that gate, and an edit must pass a dry-run of `apply_fit_overrides` (otherwise **422**);
  3. it then flips the status with a compare-and-set `UPDATE … WHERE status='awaiting_approval'`. Of two concurrent resumes exactly one wins, and the other gets 409.

  Only then does it spawn `Command(resume=…)`.
- **Context:** Invalid input reaching the node would raise inside the graph and mark the run `failed`, losing a run that was only waiting for a correct answer.
- **Consequences:** A bad edit leaves the run paused and answerable.

## 2026-11-15 — Status is derived from the checkpoint after every run
- **Decision:** `status_from_snapshot()` gives:
  - a pending gate interrupt → `awaiting_approval`;
  - pending nodes but no gate → `running` (interrupted mid-run);
  - `rejection` in state → `rejected`;
  - otherwise → `completed`.

  The runner applies it whenever `ainvoke` returns. Startup recovery uses it too, so a row stuck at `running` while its checkpoint is paused, for example after a crash between the status flip and the resume, is repaired to `awaiting_approval` without running anything.
- **Consequences:** The row and the checkpoint can't drift apart permanently. `pending_review` is shown only while the row says `awaiting_approval`, because the old interrupt stays in the checkpoint until the gate node finishes.

---

## 2026-11-16 — Phase 5: claim checker = code checks + LLM judge, bounded rewrites
- **Decision:** Each tailored bullet (`tb-N`) and letter paragraph (`p-N`) is a unit that cites its sources (CV IDs, plus company-fact IDs for the letter).
  - **Code checks first:** cited IDs must exist, bullets must cite at least one CV item, and every number in the text must appear in the cited sources' text.
  - **Then the LLM judges** each unit against only its own cited text. A unit the LLM doesn't return counts as unsupported.
  - **Failures go back to the drafting agent** as `<claim_check_failures>`, at most `CLAIM_CHECK_MAX_REWRITES` (2) times. After that, unsupported units are **dropped**, with a warning, before the human sees them.
- **Context:** PLAN's done-when: a fabricated claim must be caught and removed or rewritten. The code layer catches invented numbers and IDs even when the LLM judge is wrong (tested).
- **Alternatives:** LLM-only checking (misses numbers it is lenient about); retrying without limit (cost, possible loop).
- **Consequences:** Derived numbers ("5+ years" from the dates) fail the number check, and the prompts tell the writers to avoid them. Conservative by design.

## 2026-11-16 — Research: SearchProvider interface; default is posting-only
- **Decision:** `research_company()` builds the brief from sources: the job posting, plus results from a `SearchProvider` when one is configured. Every fact cites a source ID, and facts citing unknown sources are dropped. The default `NoSearchProvider` returns nothing. A search failure falls back to the posting with a warning.
- **Context:** Anthropic's web-search tool returns encrypted page content plus citations, and citations can't be combined with structured outputs, so it can't feed a structured, source-checked brief. A third-party search API would mean another key and dependency that nobody has asked for yet.
- **Consequences:** Out of the box the "research" covers only what the posting says. To add real search, write one provider class and pass it to `build_graph(search=...)`.

## 2026-11-16 — Content gate: approve / edit / regenerate / reject
- **Decision:** One `content_review` gate after both drafts, as in PLAN's graph, rather than separate gates for bullets and letter.
  - `edit` replaces the text of a `tb-N` or `p-N` item; its citations are kept, and it is marked `author: "human"`. **Edited text is not re-checked:** it's the candidate's own words about themselves.
  - `regenerate` (with feedback) goes back to `tailor_bullets` with fresh rewrite budgets and the feedback in every later drafting prompt.
  - Each gate rejects the edit type of the other gate (422).
- **Consequences:** Phase 6's editor can send `text_edits` directly.

---

## 2026-11-16 — Phase 6: frontend shape
- **Decision:** One page, no router. Vite + React 19 + TS (strict) + Tailwind 4, with no component library. Types are generated from the backend's OpenAPI (`npm run gen:api` reads `docs/openapi.json`), plus a ~50-line `fetch` client. `diff` (jsdiff) is the only runtime dependency beyond React and Tailwind, used for the word-level bullet diff.
- **Flow:** upload CV → paste job → steps panel polled every 1.5 s while `running` (polling stops while waiting for the user) → fit review → content review → export (copy / download .txt). `?cv=&app=` in the URL means a refresh resumes where you were.
- **Alternatives:** SSE/WebSockets (more backend work; polling a handful of runs is fine); a router and a state library (nothing needs them yet).
- **Consequences:** Optional fields in the generated types (Pydantic default → not `required`) are handled with `?? []` at the few places that read lists.

## 2026-11-16 — `/api` prefix via proxy; nginx in Docker
- **Decision:** The browser calls `/api/*`. The Vite dev server, and nginx in the frontend image, strip the prefix and proxy to the API, so the API needs no CORS. The frontend image is a two-stage node → nginx build, exposed on port 8080.

## 2026-11-16 — `LLM_MOCK=true` for demos and end-to-end runs
- **Decision:** `MockLLMClient` (app/core/mock_llm.py) returns the same canned sample data for every input, after `LLM_MOCK_DELAY_SECONDS` (default 0.8 s), so the UI visibly steps through the pipeline. The tests import the same samples, so there's one copy.
- **Consequences:** In mock mode the parsed CV is always "Jordan Rivera", whatever you upload. It's a demo switch, not a fallback.

## 2026-11-16 — `CVRead.evidence`
- **Decision:** The CV response includes `evidence` (`ParsedCV.evidence_index()`), so the UI can show the text behind a cited ID (fit evidence, bullet diffs, the override picker) without copying the ID logic into TypeScript.

---

## 2026-11-16 — Phase 7: evals with an independent judge
- **Decision:** The fabrication metric uses a **separate judge**: a different prompt that reads the **raw CV text** and the job posting rather than the pipeline's parsed IDs and citations. The pipeline's own claim checker is therefore graded by something that doesn't share its assumptions. A unit the judge skips counts as fabricated, and a code check requires every number to appear in the CV or the posting. The judge uses the same `ANTHROPIC_MODEL` by default.
- **Dataset:** 12 synthetic pairs: 4 jobs × (strong, medium, weak). Fit is measured by **ordering within a job** rather than by absolute score bands, because the score's scale is ours to choose but its ranking isn't. Keyword coverage counts only keywords the CV supports, so it never rewards fabrication.
- **Runner:** `uv run --project backend python -m evals.run` from the repo root. `evals/__init__.py` puts `backend/` on `sys.path`, so the evals drive the real app code. `--mock` runs the whole harness for free, and the threshold isn't enforced in mock mode.
- **Alternatives:** reusing the claim checker as the metric (circular); LLM-only judging (misses numbers); absolute fit-score bands (they encode arbitrary calibration).
- **Consequences:** The judge is an LLM and can err in either direction. Flagged units are listed verbatim in the report so a human can audit them.

## 2026-11-16 — Number check ignores digits inside identifiers
- **Decision:** The code number check (claim checker and judge) now extracts quantities only where the digits don't follow a word character: `(?<!\w)\d+…`. So `40%`, `2M`, `2,000` and `3.12` count, while `HL7`, `p95`, `K8s`, `EC2` and `S3` don't.
- **Context:** The first mock eval run flagged "7" from "HL7". A real bullet saying "K8s" while citing "Kubernetes" would have triggered pointless rewrites.

---

## 2026-11-16 — Phase 8: deploy on Render via a Blueprint; public demo in mock mode
- **Decision (user's choice):** `render.yaml` defines `hireflow-api` and `hireflow-web` (both Docker web services) plus a managed Postgres 16 (`hireflow-db`, `ipAllowList: []`, private network only). The API runs `numInstances: 1` because pipeline runs live in its process. `LLM_MOCK=true` by default, so the public demo costs nothing. `ANTHROPIC_API_KEY` is a `sync: false` dashboard secret.
- **Alternatives considered:** Fly.io (more setup, paid managed Postgres), Railway (config lives in the dashboard), a VPS with compose (Postgres not managed).
- **Consequences:** Free instances sleep when idle. Runs interrupted by sleep resume on startup (Phase 3). Free Postgres is time-limited, so it must be upgraded to keep data.

## 2026-11-16 — Images: one artifact for compose and Render
- **Decision:** The API image is multi-stage: uv resolves the dependencies, then a plain `python:3.12-slim` runtime copies the venv. It runs as a non-root user, has a `HEALTHCHECK`, listens on `$PORT` (default 8000), and runs `alembic upgrade head` before uvicorn, which is safe with one instance. The frontend's nginx config is a template rendered at startup from `PORT` (default 80) and `API_HOSTPORT` (`api:8000` in compose, Render's private `host:port` from `fromService`). `DATABASE_URL` values of the form `postgres://` or `postgresql://` are rewritten to `postgresql+asyncpg://` in Settings.
- **Consequences:** The same images run locally and on Render. Health checks live in the Dockerfiles (compose relies on them).

## 2026-11-16 — CI
- **Decision:** GitHub Actions with three jobs:
  - **backend:** uv, ruff on backend + evals, pytest **with a Postgres 16 service and `TEST_DATABASE_URL`** (the first place the Postgres-only tests run), the eval-harness tests, and a check that `docs/openapi.json` is up to date;
  - **frontend:** a check that the generated `schema.ts` is up to date, then lint, typecheck, Vitest and build;
  - **images:** both Docker builds.
- **Consequences:** The two drift checks keep the backend, the spec and the TS types in step.
