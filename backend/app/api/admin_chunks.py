import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DatabaseSession, get_current_user
from app.models.entities import ChunkRecord, Document, User
from app.schemas.documents import ChunkResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/chunks", response_model=list[ChunkResponse])
async def list_chunks(
    document_id: Annotated[uuid.UUID, Query()],
    user: Annotated[User, Depends(get_current_user)],
    session: DatabaseSession,
) -> list[ChunkResponse]:
    document = await session.get(Document, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    records = await session.scalars(
        select(ChunkRecord)
        .where(ChunkRecord.document_id == document_id)
        .order_by(ChunkRecord.chunk_index)
    )
    return [ChunkResponse.from_record(record) for record in records]
