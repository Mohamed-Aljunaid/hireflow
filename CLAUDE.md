# CLAUDE.md — HireFlow

HireFlow: the user uploads a CV and pastes a job posting. A LangGraph multi-agent pipeline parses the job, researches the company, scores fit, tailors CV bullets (never inventing experience) and writes a cover letter. It pauses for human approval at key steps.

These rules are permanent. Follow them in every session.

## Stack (do not substitute)
- **Backend:** Python 3.12, FastAPI, Pydantic v2
- **Database:** PostgreSQL 16, SQLAlchemy 2 (async) + Alembic migrations
- **Agents:** LangGraph with the Postgres checkpointer (`langgraph-checkpoint-postgres`)
- **LLM:** Anthropic SDK. Model name and API key come from env (`ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY`). Never hardcode either.
- **Frontend:** React + Vite + TypeScript + Tailwind
- **Runtime:** Docker Compose (api, db, frontend)

## Environment rules (hard)
- Use **uv** for ALL Python work: `uv init`, `uv add`, `uv run`, `uv sync`, `uv run pytest`, `uv run ruff`, `uv run alembic`. **Never use pip** (no `pip install`, no `uv pip`, no `python -m pip`).
- **Never write anything to the C: drive.** That includes caches, temp files, virtualenvs and Python installs. Keep everything under `E:\ai-agent-portfolio\hireflow` or another E: path. Before running uv, set:
  - `UV_CACHE_DIR=E:\ai-agent-portfolio\.uv-cache`
  - `UV_PYTHON_INSTALL_DIR=E:\ai-agent-portfolio\.uv-python`
  - Put the venv in the project (`backend/.venv`), the uv default.
  - Point npm's cache at E: too (`npm config set cache E:\ai-agent-portfolio\.npm-cache --location=project`).
- Secrets live only in `.env`, which is gitignored. Commit `.env.example` with placeholder values.

## Layout
```
backend/
  app/
    api/        # FastAPI routers, request/response schemas
    core/       # config (pydantic-settings), logging, LLM client factory
    db/         # SQLAlchemy models, session, Alembic env
    services/   # business logic (CV parsing, storage, orchestration glue)
    agents/     # LangGraph nodes, state, graph, prompts, output models
  tests/
  alembic/
  pyproject.toml
frontend/
  src/
evals/          # datasets + eval runners
docs/
  decisions.md  # architecture decision log
docker-compose.yml
.env.example
PLAN.md
```

## LLM rules
- Every LLM output that feeds another step **must be structured**: a Pydantic v2 model, enforced through Anthropic tool use / structured output and validated on receipt. Free text is allowed only for final user-facing prose (the cover letter body), and even that is wrapped in a model.
- All LLM calls go through one client wrapper in `app/core/` so tests can mock it in one place.
- **No fabrication:** tailored bullets and cover letters may only rephrase, reorder or emphasize facts present in the parsed CV. Each tailored claim carries a reference to its source CV item(s).

## Quality rules
- **Tests for everything.** pytest + pytest-asyncio. **Mock the LLM in all tests.** No network calls to Anthropic in the test suite. Use fixtures and fake clients that return canned Pydantic objects.
- **ruff** for lint and format (`uv run ruff check . && uv run ruff format .`). Code must be clean before a phase counts as done.
- Type hints everywhere. Frontend: strict TypeScript.
- Record every non-trivial decision (library choice, schema shape, trade-off) in `docs/decisions.md`: date, decision, context, alternatives, consequences.

## Workflow
- Work **one phase at a time** from `PLAN.md`.
- When the phase's **"Done when"** criteria are met (tests pass, ruff clean), **stop** and report. Do not start the next phase without the user's go-ahead.
- Do not add scope beyond the current phase.
