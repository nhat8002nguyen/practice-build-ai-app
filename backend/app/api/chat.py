import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.memory import append_exchange, load_history
from app.agents.runner import run_agent
from app.agents.tools import ToolContext
from app.api.deps import DatabaseSession, get_current_user
from app.api.deps_rag import EmbedderDep, LLMDep, Store
from app.core.config import settings
from app.core.rate_limit import RateLimiterDep, chat_policy
from app.models.entities import ChatSession, User
from app.rag.generate import generate_answer
from app.rag.retrieve import hybrid_retrieve
from app.schemas.chat import (
    CitationResponse,
    MessageRequest,
    MessageResponse,
    MetricsResponse,
    SessionResponse,
)
from app.services.llm import LLMError
from app.services.metrics import log_query_metrics

router = APIRouter(prefix="/chat", tags=["chat"])
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/sessions", response_model=SessionResponse)
async def create_session(user: CurrentUser, session: DatabaseSession) -> SessionResponse:
    chat_session = ChatSession(user_id=user.id)
    session.add(chat_session)
    await session.commit()
    return SessionResponse(id=chat_session.id)


async def _answer_with_agent(
    content: str,
    history: list[dict[str, str]],
    started: float,
    ctx: ToolContext,
) -> MessageResponse:
    try:
        result = await run_agent(ctx, ctx.llm, content, history)
    except LLMError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Language model unavailable"
        ) from None
    await append_exchange(ctx.session, ctx.session_id, content, result.answer)
    return MessageResponse(
        answer=result.answer,
        refused=result.refused,
        citations=[CitationResponse(**c) for c in result.citations],
        metrics=MetricsResponse(
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        ),
        status="awaiting_human" if result.awaiting_human else "answered",
        ticket_id=uuid.UUID(result.ticket_id) if result.ticket_id else None,
    )


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
async def send_message(
    session_id: uuid.UUID,
    body: MessageRequest,
    user: CurrentUser,
    session: DatabaseSession,
    store: Store,
    embedder: EmbedderDep,
    llm: LLMDep,
    limiter: RateLimiterDep,
) -> MessageResponse:
    await limiter.enforce(chat_policy(), str(user.id))
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")

    started = time.perf_counter()
    history = await load_history(session, session_id, settings.chat_history_turns)
    if body.mode == "agent":
        return await _answer_with_agent(
            body.content,
            history,
            started,
            ToolContext(
                session=session,
                store=store,
                embedder=embedder,
                llm=llm,
                user_id=user.id,
                session_id=session_id,
                thread_id=uuid.uuid4().hex,
            ),
        )
    chunks = await hybrid_retrieve(
        body.content,
        session=session,
        store=store,
        embedder=embedder,
        owner_user_id=user.id,
        dense_weight=settings.retrieval_dense_weight,
    )
    try:
        answer = await generate_answer(body.content, chunks, history, llm=llm)
    except LLMError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Language model unavailable"
        ) from None
    await append_exchange(session, session_id, body.content, answer.text)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    log_query_metrics(
        query_id=str(uuid.uuid4()),
        retrieved_ids=[c.chunk_id for c in chunks],
        scores=[round(c.score, 4) for c in chunks],
        latency_ms=latency_ms,
        prompt_tokens=answer.usage.prompt_tokens,
        completion_tokens=answer.usage.completion_tokens,
        model=llm.model,
    )
    return MessageResponse(
        answer=answer.text,
        refused=answer.refused,
        citations=[CitationResponse(**vars(c)) for c in answer.citations],
        metrics=MetricsResponse(
            latency_ms=latency_ms,
            prompt_tokens=answer.usage.prompt_tokens,
            completion_tokens=answer.usage.completion_tokens,
        ),
    )
