import logging
import uuid
from collections.abc import Callable

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChunkRecord, Document
from app.rag.chunking import Chunk, chunk_text
from app.rag.embeddings import Embedder
from app.rag.normalize import normalize_text
from app.rag.store import ChunkPoint, QdrantStore


logger = logging.getLogger(__name__)


class EmptyDocumentError(ValueError):
    pass


class IndexingError(RuntimeError):
    pass


async def ingest_document(
    session: AsyncSession,
    store: QdrantStore,
    embedder: Embedder,
    *,
    owner_user_id: uuid.UUID,
    filename: str,
    source_type: str,
    source_uri: str | None,
    text: str,
    strategy: str,
    chunker: Callable[[str], list[Chunk]] | None = None,
) -> tuple[Document, list[ChunkRecord]]:
    """`chunker` overrides the named strategy's defaults (used by chunking experiments)."""
    normalized = normalize_text(text)
    chunks = chunker(normalized) if chunker else chunk_text(normalized, strategy)
    if not chunks:
        raise EmptyDocumentError("Document has no extractable text")
    vectors = await embedder.embed_documents([c.text for c in chunks])

    document = Document(
        user_id=owner_user_id,
        filename=filename,
        status="processing",
        source_type=source_type,
        source_uri=source_uri,
    )
    session.add(document)
    await session.flush()

    records: list[ChunkRecord] = []
    points: list[ChunkPoint] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        point_id = uuid.uuid4()
        records.append(
            ChunkRecord(
                document_id=document.id,
                chunk_index=chunk.index,
                content=chunk.text,
                section=chunk.section,
                strategy=chunk.strategy,
                qdrant_point_id=point_id,
                chunk_metadata={"parent_text": chunk.parent_text},
            )
        )
        points.append(
            ChunkPoint(
                id=point_id,
                vector=vector,
                payload={
                    "owner_user_id": str(owner_user_id),
                    "document_id": str(document.id),
                    "filename": filename,
                    "source_type": source_type,
                    "source_uri": source_uri,
                    "version": document.version,
                    "chunk_index": chunk.index,
                    "section": chunk.section,
                    "strategy": chunk.strategy,
                    "text": chunk.text,
                    "parent_text": chunk.parent_text,
                },
            )
        )
    session.add_all(records)
    document_id = document.id
    point_ids = [point.id for point in points]
    # Order matters: rows (processing) -> status ready -> vectors. A crash between the
    # last two leaves a ready document with no vectors (empty retrieval), never
    # searchable vectors attached to a non-ready document.
    try:
        await session.commit()
        document.status = "ready"
        await session.commit()
        await store.upsert(points)
    except Exception as error:
        await _abandon_document(session, store, document_id, point_ids)
        raise IndexingError("Could not index document") from error
    return document, records


async def _abandon_document(
    session: AsyncSession,
    store: QdrantStore,
    document_id: uuid.UUID,
    point_ids: list[uuid.UUID],
) -> None:
    """Mark the document failed and remove any partially written vectors.

    Chunk rows are deleted only when the vectors were confirmed deleted. Otherwise they
    are kept: they hold the qdrant_point_id values needed to retry the cleanup.
    """
    await session.rollback()
    vectors_removed = await _attempt(document_id, store.delete(point_ids))
    try:
        if vectors_removed:
            await session.execute(
                delete(ChunkRecord).where(ChunkRecord.document_id == document_id)
            )
        await session.execute(
            update(Document).where(Document.id == document_id).values(status="failed")
        )
        await session.commit()
    except Exception:
        logger.exception("Could not mark document %s failed", document_id)


async def _attempt(document_id: uuid.UUID, operation) -> bool:
    try:
        await operation
    except Exception:
        logger.exception("Could not delete vectors for document %s", document_id)
        return False
    return True
