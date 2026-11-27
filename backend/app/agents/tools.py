import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import Ticket
from app.rag.embeddings import Embedder
from app.rag.generate import Answer, generate_answer
from app.rag.retrieve import hybrid_retrieve
from app.rag.store import QdrantStore
from app.services.llm import LLM

PRIORITIES = ("low", "normal", "high")
TICKET_OPEN = "open"
ORDER_STUB_MISS = "miss"


class ToolError(ValueError):
    """Bad tool arguments. Reported back to the model so it can correct itself."""


@dataclass
class ToolContext:
    """Per-request dependencies the tools close over."""

    session: AsyncSession
    store: QdrantStore
    embedder: Embedder
    llm: LLM
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    thread_id: str
    search_answers: list[Answer] = field(default_factory=list)

    def take_search_answers(self) -> list[Answer]:
        answers, self.search_answers = self.search_answers, []
        return answers


async def search_knowledge(ctx: ToolContext, query: str) -> str:
    """Grounded KB lookup: same retrieval, citation checks and refusal as RAG mode."""
    chunks = await hybrid_retrieve(
        query,
        session=ctx.session,
        store=ctx.store,
        embedder=ctx.embedder,
        owner_user_id=ctx.user_id,
        dense_weight=settings.retrieval_dense_weight,
    )
    answer = await generate_answer(query, chunks, [], llm=ctx.llm)
    ctx.search_answers.append(answer)
    if answer.refused:
        return "No grounded answer found in the knowledge base."
    sources = ", ".join(sorted({c.source for c in answer.citations}))
    return f"{answer.text}\n(sources: {sources})"


async def lookup_order(ctx: ToolContext, order_id: str) -> dict[str, Any]:
    """Order stub. ORDER_STUB_MODE=miss simulates an unknown order."""
    if os.getenv("ORDER_STUB_MODE", "hit") == ORDER_STUB_MISS:
        return {"found": False, "order_id": order_id}
    return {
        "found": True,
        "order_id": order_id,
        "status": "shipped",
        "carrier": "DemoExpress",
        "eta_days": 3,
    }


async def create_ticket(ctx: ToolContext, reason: str, priority: str) -> str:
    """Open a human-review ticket. At most one per agent run, so retries are idempotent."""
    if priority not in PRIORITIES:
        raise ToolError(f"priority must be one of {', '.join(PRIORITIES)}")
    existing = await ctx.session.scalar(
        select(Ticket).where(Ticket.thread_id == ctx.thread_id)
    )
    if existing is not None:
        return str(existing.id)
    ticket = Ticket(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        subject=reason[:255],
        description=reason,
        priority=priority,
        status=TICKET_OPEN,
        thread_id=ctx.thread_id,
    )
    ctx.session.add(ticket)
    await ctx.session.commit()
    return str(ticket.id)


def _required(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing string argument '{name}'")
    return value.strip()


async def _call_search(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await search_knowledge(ctx, _required(args, "query"))


async def _call_lookup(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await lookup_order(ctx, _required(args, "order_id"))


async def _call_ticket(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await create_ticket(
        ctx, _required(args, "reason"), str(args.get("priority") or "normal")
    )


TOOL_REGISTRY: dict[str, Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]] = {
    "search_knowledge": _call_search,
    "lookup_order": _call_lookup,
    "create_ticket": _call_ticket,
}

TOOL_DESCRIPTIONS = """Tools (call at most one per turn):
- search_knowledge {"query": str}: grounded answer from the knowledge base.
- lookup_order {"order_id": str}: order status; returns found=false for unknown orders.
- create_ticket {"reason": str, "priority": "low"|"normal"|"high"}: escalate to a human."""


async def run_tool(ctx: ToolContext, name: str, args: object) -> Any:
    handler = TOOL_REGISTRY.get(name)
    if handler is None:
        raise ToolError(f"unknown tool '{name}'")
    if not isinstance(args, dict):
        raise ToolError("args must be an object")
    return await handler(ctx, args)
