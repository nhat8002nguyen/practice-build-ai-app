import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DatabaseSession
from app.api.deps_rag import EmbedderDep, LLMDep, Store
from app.core.config import settings
from app.core.rate_limit import RateLimiterDep, drafts_policy
from app.models.entities import User
from app.rag.generate import generate_answer
from app.rag.retrieve import hybrid_retrieve
from app.schemas.chat import CitationResponse
from app.services.llm import LLMError

router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftReplyRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10000)
    customer_email: str | None = Field(default=None, max_length=320)


class DraftReplyResponse(BaseModel):
    draft: str
    citations: list[CitationResponse]
    refused: bool


def _verify_secret(provided: str | None) -> None:
    configured = settings.n8n_draft_secret
    if not configured or not provided or not hmac.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid n8n secret",
        )


@router.post("/reply", response_model=DraftReplyResponse)
async def draft_reply(
    body: DraftReplyRequest,
    session: DatabaseSession,
    store: Store,
    embedder: EmbedderDep,
    llm: LLMDep,
    limiter: RateLimiterDep,
    x_n8n_secret: Annotated[str | None, Header()] = None,
) -> DraftReplyResponse:
    _verify_secret(x_n8n_secret)
    await limiter.enforce(drafts_policy(), "n8n")
    owner = await session.scalar(
        select(User).where(User.email == settings.draft_user_email)
    )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Draft owner is not configured",
        )

    query_parts = [f"Subject: {body.subject}", f"Message: {body.body}"]
    if body.customer_email:
        query_parts.insert(1, f"Customer email: {body.customer_email}")
    query = "\n".join(query_parts)
    chunks = await hybrid_retrieve(
        query,
        session=session,
        store=store,
        embedder=embedder,
        owner_user_id=owner.id,
        dense_weight=settings.retrieval_dense_weight,
    )
    try:
        answer = await generate_answer(query, chunks, [], llm=llm)
    except LLMError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Language model unavailable",
        ) from None

    return DraftReplyResponse(
        draft=answer.text,
        citations=[CitationResponse(**vars(c)) for c in answer.citations],
        refused=answer.refused,
    )
