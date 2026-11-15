from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.llm import AnthropicLLMClient, LLMClient
from app.db.session import get_session
from app.services.pipeline_runner import PipelineRunner


@lru_cache
def _default_llm_client() -> AnthropicLLMClient:
    return AnthropicLLMClient(get_settings())


def get_llm_client() -> LLMClient:
    return _default_llm_client()


def get_runner(request: Request) -> PipelineRunner:
    """The runner created in the app lifespan (see app/main.py)."""
    return request.app.state.runner


SessionDep = Annotated[AsyncSession, Depends(get_session)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RunnerDep = Annotated[PipelineRunner, Depends(get_runner)]
