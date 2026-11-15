from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.checkpointer import open_checkpointer
from app.agents.graph import build_graph
from app.api import applications, cvs, fit, health, jobs
from app.api.deps import get_llm_client
from app.api.errors import register_error_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_sessionmaker
from app.services.pipeline_runner import PipelineRunner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with open_checkpointer(settings) as checkpointer:
        graph = build_graph(get_llm_client(), settings).compile(checkpointer=checkpointer)
        runner = PipelineRunner(graph, get_sessionmaker())
        app.state.runner = runner
        await runner.resume_incomplete()
        try:
            yield
        finally:
            await runner.shutdown()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(cvs.router)
    app.include_router(jobs.router)
    app.include_router(fit.router)
    app.include_router(applications.router)
    return app


app = create_app()
