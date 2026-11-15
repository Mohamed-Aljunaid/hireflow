"""App-wide mapping of LLM failures to HTTP responses."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.llm import LLMError, LLMUnavailableError

logger = logging.getLogger(__name__)


async def _llm_unavailable(_: Request, exc: Exception) -> JSONResponse:
    logger.error("LLM unavailable: %s", exc)
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


async def _llm_error(_: Request, exc: Exception) -> JSONResponse:
    logger.warning("LLM call failed: %s", exc)
    return JSONResponse(
        {"detail": f"LLM step failed: {exc}"}, status_code=status.HTTP_502_BAD_GATEWAY
    )


def register_error_handlers(app: FastAPI) -> None:
    # Starlette resolves handlers by MRO, so the subclass wins over LLMError.
    app.add_exception_handler(LLMUnavailableError, _llm_unavailable)
    app.add_exception_handler(LLMError, _llm_error)
