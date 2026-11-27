import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings


@dataclass
class ChunkPoint:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class SearchHit:
    score: float
    payload: dict[str, Any]
    point_id: uuid.UUID | None = None


class QdrantStore:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection: str = "knowledge_chunks",
    ) -> None:
        self._client = client
        self._collection = collection
        self._create_lock = asyncio.Lock()
        self._collection_ready = False

    async def ensure_collection(self, dimensions: int) -> None:
        if self._collection_ready:
            return
        async with self._create_lock:
            if self._collection_ready:
                return
            if not await self._client.collection_exists(self._collection):
                await self._create_collection(dimensions)
            self._collection_ready = True

    async def _create_collection(self, dimensions: int) -> None:
        try:
            await self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(
                    size=dimensions, distance=models.Distance.COSINE
                ),
            )
        except (UnexpectedResponse, ValueError):
            # Another worker may have created it between our check and create.
            if not await self._client.collection_exists(self._collection):
                raise

    async def delete(self, point_ids: list[uuid.UUID]) -> None:
        if not point_ids or not await self._client.collection_exists(self._collection):
            return
        await self._client.delete(
            self._collection,
            points_selector=models.PointIdsList(points=[str(i) for i in point_ids]),
        )

    async def upsert(self, points: list[ChunkPoint]) -> None:
        if not points:
            return
        await self.ensure_collection(len(points[0].vector))
        await self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(id=str(p.id), vector=p.vector, payload=p.payload)
                for p in points
            ],
        )

    async def search(
        self,
        vector: list[float],
        owner_user_id: uuid.UUID,
        limit: int = 5,
    ) -> list[SearchHit]:
        if not await self._client.collection_exists(self._collection):
            return []
        response = await self._client.query_points(
            self._collection,
            query=vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="owner_user_id",
                        match=models.MatchValue(value=str(owner_user_id)),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )
        return [
            SearchHit(p.score, p.payload or {}, uuid.UUID(str(p.id)))
            for p in response.points
        ]


def build_store() -> QdrantStore:
    return QdrantStore(
        AsyncQdrantClient(url=settings.qdrant_url),
        settings.qdrant_collection,
    )
