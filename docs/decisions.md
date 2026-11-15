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
