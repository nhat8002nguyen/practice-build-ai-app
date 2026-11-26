import hashlib
import math
from typing import Protocol

from openai import AsyncOpenAI

from app.core.config import settings
from app.rag.terms import content_tokens

_OPENAI_BATCH_SIZE = 100


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key, timeout=settings.llm_timeout_seconds, max_retries=1
        )
        self._model = model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _OPENAI_BATCH_SIZE):
            batch = texts[start : start + _OPENAI_BATCH_SIZE]
            response = await self._client.embeddings.create(
                model=self._model, input=batch
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder. For tests only, never production."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in content_tokens(text):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def build_embedder() -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the openai embedder")
    return OpenAIEmbedder(settings.openai_api_key, settings.embedding_model)
