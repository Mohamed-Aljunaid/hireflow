"""AnthropicLLMClient against a mocked SDK client: no network."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.schemas.cv import CVExtraction
from app.core.config import Settings
from app.core.llm import (
    FALLBACK_BETA,
    AnthropicLLMClient,
    LLMError,
    LLMRefusalError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tests.fakes import (
    all_supported,
    sample_company_research,
    sample_cover_letter_draft,
    sample_extraction,
    sample_fit_assessment,
    sample_job_extraction,
    sample_tailoring_draft,
)


class FakeBetaMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def make_client(response: Any, **settings: Any) -> tuple[AnthropicLLMClient, FakeBetaMessages]:
    messages = FakeBetaMessages(response)
    sdk = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    cfg = Settings(_env_file=None, anthropic_model="test-model", **settings)
    return AnthropicLLMClient(cfg, client=sdk), messages  # type: ignore[arg-type]


def response(stop_reason: str = "end_turn", parsed: Any = None, stop_details: Any = None) -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=stop_details,
        parsed_output=parsed,
        model="test-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


async def test_returns_parsed_output_and_sends_expected_request() -> None:
    expected = sample_extraction()
    client, messages = make_client(response(parsed=expected), anthropic_effort="high")

    result = await client.structured(system="sys", user="hello", output_model=CVExtraction)

    assert result is expected
    kw = messages.kwargs
    assert kw["model"] == "test-model"
    assert kw["system"] == "sys"
    assert kw["messages"] == [{"role": "user", "content": "hello"}]
    assert kw["output_format"] is CVExtraction
    assert kw["output_config"] == {"effort": "high"}
    assert kw["betas"] == [FALLBACK_BETA]
    assert kw["fallbacks"] == "default"


async def test_per_call_effort_overrides_default() -> None:
    client, messages = make_client(response(parsed=sample_extraction()), anthropic_effort="low")
    await client.structured(system="s", user="u", output_model=CVExtraction, effort="xhigh")
    assert messages.kwargs["output_config"] == {"effort": "xhigh"}


async def test_fallback_can_be_disabled() -> None:
    client, messages = make_client(
        response(parsed=sample_extraction()), anthropic_refusal_fallback=False
    )
    await client.structured(system="s", user="u", output_model=CVExtraction)
    assert "fallbacks" not in messages.kwargs
    assert "betas" not in messages.kwargs


async def test_refusal_raises() -> None:
    details = SimpleNamespace(category="cyber", explanation="x")
    client, _ = make_client(response("refusal", stop_details=details))
    with pytest.raises(LLMRefusalError, match="cyber"):
        await client.structured(system="s", user="u", output_model=CVExtraction)


async def test_max_tokens_raises() -> None:
    client, _ = make_client(response("max_tokens"))
    with pytest.raises(LLMTruncatedError):
        await client.structured(system="s", user="u", output_model=CVExtraction)


async def test_real_sdk_request_and_parse_via_mock_transport() -> None:
    """Exercises the real SDK (schema conversion, headers, parsing) with a mocked HTTP layer."""
    import json

    import httpx2
    from anthropic import AsyncAnthropic

    captured: dict[str, Any] = {}
    expected = sample_extraction()

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        captured["beta"] = request.headers.get("anthropic-beta")
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": expected.model_dump_json()}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    sdk = AsyncAnthropic(
        api_key="test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    client = AnthropicLLMClient(Settings(_env_file=None, anthropic_model="test-model"), client=sdk)

    result = await client.structured(system="sys", user="cv text", output_model=CVExtraction)

    assert result == expected
    body = captured["body"]
    assert body["model"] == "test-model"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "contact" in body["output_config"]["format"]["schema"]["properties"]
    assert FALLBACK_BETA in captured["beta"]


@pytest.mark.parametrize(
    "instance",
    [
        sample_extraction(),
        sample_job_extraction(),
        sample_fit_assessment(),
        sample_company_research(),
        sample_tailoring_draft(),
        sample_cover_letter_draft(),
        all_supported("[tb-1] x\n[p-1] y"),
    ],
    ids=lambda m: type(m).__name__,
)
async def test_every_agent_output_model_round_trips_through_real_sdk(instance: Any) -> None:
    """Each output model converts to a JSON schema the SDK accepts and parses back."""
    import json

    import httpx2
    from anthropic import AsyncAnthropic

    sent: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": instance.model_dump_json()}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    sdk = AsyncAnthropic(
        api_key="k", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    client = AnthropicLLMClient(Settings(_env_file=None), client=sdk)
    result = await client.structured(system="s", user="u", output_model=type(instance))

    assert result == instance
    schema = sent["output_config"]["format"]["schema"]
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, LLMUnavailableError),
        (403, LLMUnavailableError),
        (429, LLMUnavailableError),
        (529, LLMUnavailableError),
        (500, LLMUnavailableError),
        (400, LLMError),
    ],
)
async def test_sdk_http_errors_are_wrapped(status_code: int, expected: type[LLMError]) -> None:
    import httpx2
    from anthropic import AsyncAnthropic

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code, json={"type": "error", "error": {"type": "x", "message": "boom"}}
        )

    sdk = AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    client = AnthropicLLMClient(Settings(_env_file=None), client=sdk)
    with pytest.raises(expected) as info:
        await client.structured(system="s", user="u", output_model=CVExtraction)
    if expected is LLMError:
        assert not isinstance(info.value, LLMUnavailableError)


async def test_connection_error_is_wrapped() -> None:
    import httpx2
    from anthropic import AsyncAnthropic

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    sdk = AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    client = AnthropicLLMClient(Settings(_env_file=None), client=sdk)
    with pytest.raises(LLMUnavailableError):
        await client.structured(system="s", user="u", output_model=CVExtraction)


async def test_missing_credentials_is_wrapped() -> None:
    class NoCreds:
        async def parse(self, **kwargs: Any) -> Any:
            raise TypeError('"Could not resolve authentication method. Expected one of api_key"')

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=NoCreds()))
    client = AnthropicLLMClient(Settings(_env_file=None), client=sdk)  # type: ignore[arg-type]
    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        await client.structured(system="s", user="u", output_model=CVExtraction)


async def test_unrelated_type_error_is_not_swallowed() -> None:
    class Broken:
        async def parse(self, **kwargs: Any) -> Any:
            raise TypeError("unexpected keyword argument")

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=Broken()))
    client = AnthropicLLMClient(Settings(_env_file=None), client=sdk)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await client.structured(system="s", user="u", output_model=CVExtraction)


async def test_missing_parsed_output_raises() -> None:
    client, _ = make_client(response("end_turn", parsed=None))
    with pytest.raises(LLMError):
        await client.structured(system="s", user="u", output_model=CVExtraction)
