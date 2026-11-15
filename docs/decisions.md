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
