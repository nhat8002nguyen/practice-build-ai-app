import asyncio
import uuid
from unittest.mock import AsyncMock

from qdrant_client import AsyncQdrantClient

from app.rag.store import ChunkPoint, QdrantStore


OWNER = uuid.UUID(int=1)


def point() -> ChunkPoint:
    return ChunkPoint(uuid.uuid4(), [1.0, 0.0, 0.0], {"owner_user_id": str(OWNER)})


def test_concurrent_first_upserts_create_collection_once():
    async def run() -> int:
        client = AsyncQdrantClient(":memory:")
        client.create_collection = AsyncMock(wraps=client.create_collection)
        store = QdrantStore(client, "knowledge_chunks")
        await asyncio.gather(*(store.upsert([point()]) for _ in range(5)))
        return client.create_collection.await_count

    assert asyncio.run(run()) == 1


def test_collection_created_by_another_process_is_tolerated():
    async def run() -> None:
        client = AsyncQdrantClient(":memory:")
        other = QdrantStore(client, "knowledge_chunks")
        await other.ensure_collection(3)
        client.collection_exists = AsyncMock(side_effect=[False, True])
        await QdrantStore(client, "knowledge_chunks").ensure_collection(3)

    asyncio.run(run())


def test_delete_removes_points():
    async def run() -> int:
        store = QdrantStore(AsyncQdrantClient(":memory:"), "knowledge_chunks")
        kept, removed = point(), point()
        await store.upsert([kept, removed])
        await store.delete([removed.id])
        hits = await store.search([1.0, 0.0, 0.0], OWNER, limit=5)
        return len(hits)

    assert asyncio.run(run()) == 1
