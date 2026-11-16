"""The single entry point for LLM calls.

Every call returns a validated Pydantic model. Tests replace `LLMClient` with a fake
(see tests/conftest.py), so no test ever reaches the Anthropic API.
"""

import logging
from typing import Protocol

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.core.config import Effort, Settings

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The LLM call failed or returned unusable output."""


class LLMRefusalError(LLMError):
    """The model declined the request."""


class LLMTruncatedError(LLMError):
    """Output hit max_tokens before the structured output was complete."""


class LLMUnavailableError(LLMError):
    """The LLM service could not be reached or used: credentials, rate limits, outages."""


class LLMClient(Protocol):
    async def structured[T: BaseModel](
        self, *, system: str, user: str, output_model: type[T], effort: Effort | None = None
    ) -> T:
        """Return a validated `output_model`. `effort` overrides the configured default."""
        ...


class AnthropicLLMClient:
    def __init__(self, settings: Settings, client: AsyncAnthropic | None = None) -> None:
        api_key = (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        self._client = client or AsyncAnthropic(api_key=api_key)
        self._model = settings.anthropic_model
        self._effort = settings.anthropic_effort
        self._max_tokens = settings.anthropic_max_tokens
        self._fallback = settings.anthropic_refusal_fallback
        # Running totals for this client (evals report them; the API ignores them).
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    async def structured[T: BaseModel](
        self, *, system: str, user: str, output_model: type[T], effort: Effort | None = None
    ) -> T:
        kwargs: dict = {}
        if self._fallback:
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

        try:
            response = await self._client.beta.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
                output_config={"effort": effort or self._effort},
                **kwargs,
            )
        except ValidationError as exc:
            raise LLMError(f"structured output failed validation: {exc}") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMUnavailableError(f"Anthropic credentials rejected: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("Anthropic rate limit reached; retry later") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailableError(f"Anthropic API error {exc.status_code}") from exc
            raise LLMError(
                f"Anthropic API rejected the request ({exc.status_code}): {exc}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"could not reach Anthropic API: {exc}") from exc
        except TypeError as exc:
            # The SDK raises TypeError when no credential source resolves.
            if "authentication" not in str(exc).lower():
                raise
            raise LLMUnavailableError(
                "no Anthropic credentials configured (set ANTHROPIC_API_KEY)"
            ) from exc

        self.usage["calls"] += 1
        self.usage["input_tokens"] += response.usage.input_tokens
        self.usage["output_tokens"] += response.usage.output_tokens
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMRefusalError(f"model refused the request (category={category})")
        if response.stop_reason == "max_tokens":
            raise LLMTruncatedError("structured output truncated at max_tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError(f"no structured output (stop_reason={response.stop_reason})")
        logger.info(
            "llm call ok model=%s output=%s in_tokens=%s out_tokens=%s",
            response.model,
            output_model.__name__,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return parsed
