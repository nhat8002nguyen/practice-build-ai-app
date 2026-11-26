import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class CrawlRequest(BaseModel):
    url: str


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    source_type: str
    source_uri: str | None
    status: str
    strategy: str
    chunk_count: int


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    section: str | None
    strategy: str | None
    qdrant_point_id: uuid.UUID | None
    parent_text: str | None = None

    @classmethod
    def from_record(cls, record: Any) -> "ChunkResponse":
        response = cls.model_validate(record)
        response.parent_text = (record.chunk_metadata or {}).get("parent_text")
        return response
