import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from openai import AsyncOpenAI, OpenAIError

from app.core.config import settings


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


class LLM(Protocol):
    model: str

    async def complete(
        self, system: str, messages: list[dict[str, str]]
    ) -> LLMResult: ...


class OpenAILLM:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key, timeout=settings.llm_timeout_seconds, max_retries=1
        )
        self.model = model

    async def complete(
        self, system: str, messages: list[dict[str, str]]
    ) -> LLMResult:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except OpenAIError as error:
            raise LLMError("LLM request failed") from error
        usage = response.usage
        return LLMResult(
            text=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 1024
_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Claude has no JSON mode and sometimes wraps the object in a markdown fence."""
    match = _CODE_FENCE.match(text.strip())
    return match.group(1) if match else text


class AnthropicLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(
            timeout=settings.llm_timeout_seconds
        )
        self.model = model

    async def complete(
        self, system: str, messages: list[dict[str, str]]
    ) -> LLMResult:
        try:
            response = await self._client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                },
                json={
                    "model": self.model,
                    "max_tokens": ANTHROPIC_MAX_TOKENS,
                    "temperature": 0,
                    "system": system,
                    "messages": messages,
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LLMError("LLM request failed") from error
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        )
        usage = body.get("usage") or {}
        return LLMResult(
            text=_strip_code_fence(text),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
        )


def active_model() -> str:
    if settings.llm_provider == "anthropic":
        return settings.anthropic_model
    return settings.llm_model


def build_llm() -> LLM:
    provider = settings.llm_provider
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for the LLM")
        return AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model)
    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is required for the LLM")
        return OpenAILLM(settings.openai_api_key, settings.llm_model)
    raise LLMError(f"Unknown LLM_PROVIDER: {provider}")


class ConfiguredLLM:
    """Defers client construction to the first model call.

    Requests that never reach the model (refusals, unsupported modes) must not
    fail just because the LLM is not configured.
    """

    def __init__(self) -> None:
        self._delegate: LLM | None = None

    @property
    def model(self) -> str:
        return active_model()

    async def complete(
        self, system: str, messages: list[dict[str, str]]
    ) -> LLMResult:
        if self._delegate is None:
            self._delegate = build_llm()
        return await self._delegate.complete(system, messages)
