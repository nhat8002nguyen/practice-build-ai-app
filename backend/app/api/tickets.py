import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import append_assistant_message
from app.agents.runner import resume_agent
from app.agents.tools import TICKET_OPEN, ToolContext
from app.api.deps import DatabaseSession, get_current_user
from app.api.deps_rag import EmbedderDep, LLMDep, Store
from app.models.entities import Ticket, User
from app.schemas.tickets import ResolveRequest, TicketResponse

router = APIRouter(prefix="/tickets", tags=["tickets"])
CurrentUser = Annotated[User, Depends(get_current_user)]

DECISION_STATUS = {"approve": "approved", "reject": "rejected"}


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    user: CurrentUser,
    session: DatabaseSession,
    ticket_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[Ticket]:
    query = select(Ticket).where(Ticket.user_id == user.id)
    if ticket_status:
        query = query.where(Ticket.status == ticket_status)
    rows = await session.scalars(query.order_by(Ticket.created_at.desc(), Ticket.id))
    return list(rows)


@router.post("/{ticket_id}/resolve", response_model=TicketResponse)
async def resolve_ticket(
    ticket_id: uuid.UUID,
    body: ResolveRequest,
    user: CurrentUser,
    session: DatabaseSession,
    store: Store,
    embedder: EmbedderDep,
    llm: LLMDep,
) -> Ticket:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if not await _claim_ticket(session, ticket_id, body):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ticket already resolved")

    ctx = ToolContext(
        session=session,
        store=store,
        embedder=embedder,
        llm=llm,
        user_id=user.id,
        session_id=ticket.session_id,
        thread_id=ticket.thread_id or "",
    )
    try:
        answer = await resume_agent(ctx, llm, body.decision, body.note)
    except BaseException:
        await _release_ticket(session, ticket_id)
        raise
    if answer is None:
        # Paused run is gone (restart, other worker): never report a resolved HITL run.
        await _release_ticket(session, ticket_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="The paused agent run can no longer be resumed; the ticket stays open",
        )
    if ticket.session_id:
        await append_assistant_message(session, ticket.session_id, answer)
    await session.refresh(ticket)
    return ticket


async def _claim_ticket(
    session: AsyncSession, ticket_id: uuid.UUID, body: ResolveRequest
) -> bool:
    """Atomically move open -> decided; only one concurrent resolver sees rowcount 1."""
    result = await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id, Ticket.status == TICKET_OPEN)
        .values(status=DECISION_STATUS[body.decision], resolution_note=body.note)
    )
    await session.commit()
    return result.rowcount == 1


async def _release_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> None:
    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status=TICKET_OPEN, resolution_note=None)
    )
    await session.commit()
