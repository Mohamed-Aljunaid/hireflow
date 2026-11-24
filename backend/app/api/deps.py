from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.llm import AnthropicLLMClient, LLMClient
from app.core.mock_llm import MockLLMClient
from app.db.session import get_session
from app.services.job_search import BASE_URL
from app.services.pipeline_runner import PipelineRunner


@lru_cache
def _default_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_mock:
        return MockLLMClient(settings.llm_mock_delay_seconds)
    return AnthropicLLMClient(settings)


def get_llm_client() -> LLMClient:
    return _default_llm_client()


def get_runner(request: Request) -> PipelineRunner:
    """The runner created in the app lifespan (see app/main.py)."""
    return request.app.state.runner


async def get_job_board() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as http:
        yield http


SessionDep = Annotated[AsyncSession, Depends(get_session)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RunnerDep = Annotated[PipelineRunner, Depends(get_runner)]
JobBoardDep = Annotated[httpx.AsyncClient, Depends(get_job_board)]
