from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import cvs, fit, health, jobs
from app.api.errors import register_error_handlers
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
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
    return app


app = create_app()
