import asyncio
import json

import httpx
import pytest

from app.core.config import settings
from app.rag.generate import generate_answer
from app.rag.retrieve import RetrievedChunk
from app.services import llm as llm_module
from app.services.llm import (
    ANTHROPIC_URL,
    AnthropicLLM,
    ConfiguredLLM,
    LLMError,
    OpenAILLM,
    active_model,
    build_llm,
)

QUOTE = "Customers may request a full refund within 14 days of purchase."


def anthropic_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def claude_reply(text: str, input_tokens: int = 90, output_tokens: int = 25) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    )


def test_anthropic_request_shape_and_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return claude_reply('{"insufficient_evidence": true}')

    llm = AnthropicLLM("sk-ant-test", "claude-haiku-4-5", anthropic_client(handler))

    result = asyncio.run(llm.complete("be brief", [{"role": "user", "content": "hi"}]))

    assert seen["url"] == ANTHROPIC_URL
    assert seen["headers"]["x-api-key"] == "sk-ant-test"
    assert seen["headers"]["anthropic-version"]
    assert seen["body"]["model"] == "claude-haiku-4-5"
    assert seen["body"]["system"] == "be brief"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert result.text == '{"insufficient_evidence": true}'
    assert (result.prompt_tokens, result.completion_tokens) == (90, 25)


def test_anthropic_strips_markdown_fence_around_json():
    llm = AnthropicLLM(
        "k", "claude-haiku-4-5", anthropic_client(lambda _: claude_reply('```json\n{"a": 1}\n```'))
    )

    result = asyncio.run(llm.complete("s", [{"role": "user", "content": "q"}]))

    assert json.loads(result.text) == {"a": 1}


@pytest.mark.parametrize(
    "response",
    [httpx.Response(529, json={"error": "overloaded"}), httpx.Response(200, text="not json")],
)
def test_anthropic_failures_become_llm_errors(response):
    llm = AnthropicLLM("k", "claude-haiku-4-5", anthropic_client(lambda _: response))

    with pytest.raises(LLMError):
        asyncio.run(llm.complete("s", [{"role": "user", "content": "q"}]))


def test_anthropic_transport_errors_become_llm_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    llm = AnthropicLLM("k", "claude-haiku-4-5", anthropic_client(handler))

    with pytest.raises(LLMError):
        asyncio.run(llm.complete("s", [{"role": "user", "content": "q"}]))


def test_claude_answer_flows_through_generate_with_verified_citation():
    chunk = RetrievedChunk("c1", "sample_policy.md", "Refunds", QUOTE, None, 0.9)
    reply = json.dumps(
        {
            "answer": "Refunds are available within 14 days of purchase.",
            "citations": [{"chunk_id": "c1", "quote": QUOTE}],
        }
    )
    llm = AnthropicLLM(
        "k", "claude-haiku-4-5", anthropic_client(lambda _: claude_reply(f"```json\n{reply}\n```"))
    )

    answer = asyncio.run(generate_answer("refund window?", [chunk], [], llm=llm))

    assert answer.refused is False
    assert answer.citations[0].quote == QUOTE
    assert (answer.usage.prompt_tokens, answer.usage.completion_tokens) == (90, 25)


def test_provider_is_selected_by_env_setting(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant")

    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert isinstance(build_llm(), OpenAILLM)
    assert active_model() == settings.llm_model

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert isinstance(build_llm(), AnthropicLLM)
    assert active_model() == settings.anthropic_model
    assert ConfiguredLLM().model == settings.anthropic_model


def test_missing_key_for_selected_provider_fails_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")

    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        build_llm()


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mystery")

    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        build_llm()


def test_configured_llm_uses_claude_end_to_end_with_mock_transport(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return claude_reply('{"insufficient_evidence": true}')

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant")
    monkeypatch.setattr(
        llm_module.httpx,
        "AsyncClient",
        lambda **_: real_client(transport=httpx.MockTransport(handler)),
    )

    result = asyncio.run(ConfiguredLLM().complete("s", [{"role": "user", "content": "q"}]))

    assert result.text == '{"insufficient_evidence": true}'
