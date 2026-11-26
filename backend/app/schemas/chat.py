import uuid
from typing import Literal

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    id: uuid.UUID


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    mode: Literal["rag", "agent"] = "rag"


class CitationResponse(BaseModel):
    chunk_id: str
    source: str
    quote: str


class MetricsResponse(BaseModel):
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


class MessageResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[CitationResponse]
    metrics: MetricsResponse
    status: Literal["answered", "awaiting_human"] = "answered"
    ticket_id: uuid.UUID | None = None
