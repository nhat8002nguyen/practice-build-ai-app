import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.deps_rag import get_embedder, get_llm, get_store
from app.core.db import Base, get_db
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.main import app
from app.rag.embeddings import HashEmbedder
from app.rag.store import QdrantStore
from app.services.llm import LLMResult


class FakeLLM:
    """Scripted LLM so CI needs no API key. Records every call it receives."""

    model = "gpt-4o-mini"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, str]]]] = []
        self.responder: Callable[[str, list[dict[str, str]]], str] = lambda *_: (
            '{"insufficient_evidence": true}'
        )

    async def complete(self, system: str, messages: list[dict[str, str]]) -> LLMResult:
        self.calls.append((system, messages))
        return LLMResult(self.responder(system, messages), 120, 30)


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder()


@pytest.fixture
def store() -> QdrantStore:
    # Real qdrant-client in local in-memory mode, so CI needs no Qdrant server.
    return QdrantStore(AsyncQdrantClient(":memory:"), "knowledge_chunks")


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "ingest.db"


@pytest.fixture
def client(db_path, store, embedder, llm, fake_redis) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    asyncio.run(prepare_database())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_embedder] = lambda: embedder
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(fake_redis)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture
def register_user(client) -> Callable[[], dict[str, str]]:
    """Registers a fresh user and returns its auth headers."""

    def register() -> dict[str, str]:
        credentials = {
            "email": f"agent-{uuid.uuid4().hex}@example.com",
            "password": "secret123",
        }
        token = client.post("/auth/register", json=credentials).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return register


@pytest.fixture(autouse=True)
def fresh_agent_checkpointer() -> Iterator[None]:
    from app.agents.runner import get_checkpointer

    get_checkpointer.cache_clear()
    yield
    get_checkpointer.cache_clear()
