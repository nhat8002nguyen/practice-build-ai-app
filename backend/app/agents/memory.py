import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Message


async def load_history(
    session: AsyncSession, session_id: uuid.UUID, turns: int
) -> list[dict[str, str]]:
    """Last `turns` user/assistant exchanges, oldest first."""
    rows = await session.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(turns * 2)
    )
    return [{"role": m.role, "content": m.content} for m in reversed(list(rows))]


async def append_exchange(
    session: AsyncSession,
    session_id: uuid.UUID,
    user_content: str,
    assistant_content: str,
) -> None:
    # Explicit timestamps: now() is constant within a Postgres transaction, which
    # would leave the pair in arbitrary order when loading history.
    asked_at = datetime.now(UTC)
    session.add_all(
        [
            Message(
                session_id=session_id,
                role="user",
                content=user_content,
                created_at=asked_at,
            ),
            Message(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                created_at=asked_at + timedelta(microseconds=1),
            ),
        ]
    )
    await session.commit()


async def append_assistant_message(
    session: AsyncSession, session_id: uuid.UUID, content: str
) -> None:
    session.add(
        Message(
            session_id=session_id,
            role="assistant",
            content=content,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
