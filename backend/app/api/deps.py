from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.llm import AnthropicLLMClient, LLMClient
from app.db.session import get_session


@lru_cache
def _default_llm_client() -> AnthropicLLMClient:
    return AnthropicLLMClient(get_settings())


def get_llm_client() -> LLMClient:
    return _default_llm_client()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
LLMDep = Annotated[LLMClient, Depends(get_llm_client)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
