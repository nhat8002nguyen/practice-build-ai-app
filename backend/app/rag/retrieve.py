import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChunkRecord, Document
from app.rag.embeddings import Embedder
from app.rag.store import QdrantStore

READY = "ready"
CANDIDATE_POOL = 20
BM25_K1 = 1.5
BM25_B = 0.75

_WORD = re.compile(r"\w+")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it my of on or "
    "our the to was we what when where which who why will with you your".split()
)


@dataclass
class RetrievedChunk:
    chunk_id: str
    source: str
    section: str | None
    text: str
    parent_text: str | None
    score: float


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


def bm25_scores(query: str, documents: dict[str, str]) -> list[tuple[str, float]]:
    """BM25 over an in-memory corpus, scaled so the best match scores 1.0.

    The corpus is one user's chunks, so computing it per query is cheap at SMB scale.
    """
    query_terms = set(tokenize(query))
    tokenized = {doc_id: tokenize(text) for doc_id, text in documents.items()}
    if not query_terms or not tokenized:
        return []
    average_length = sum(len(t) for t in tokenized.values()) / len(tokenized) or 1.0
    document_frequency = Counter(
        term for tokens in tokenized.values() for term in query_terms & set(tokens)
    )

    raw: dict[str, float] = {}
    for doc_id, tokens in tokenized.items():
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            if not frequency:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(tokenized) - df + 0.5) / (df + 0.5))
            norm = 1 - BM25_B + BM25_B * len(tokens) / average_length
            score += idf * frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * norm)
        if score > 0:
            raw[doc_id] = score
    if not raw:
        return []
    best = max(raw.values())
    return sorted(((d, s / best) for d, s in raw.items()), key=lambda x: -x[1])


def merge_hybrid(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    dense_weight: float,
    k: int,
) -> list[tuple[str, float]]:
    """Merge dense and sparse scores on [0, 1].

    A hit present in only one channel keeps that channel's score. When both channels
    hit, the score is max(dense, sparse, weighted sum) so a weak second channel cannot
    pull a single-channel clearance under the retrieval refusal gate.
    """
    dense_scores = dict(dense)
    sparse_scores = dict(sparse)
    combined: dict[str, float] = {}
    for doc_id in dense_scores.keys() | sparse_scores.keys():
        has_dense = doc_id in dense_scores
        has_sparse = doc_id in sparse_scores
        if has_dense and has_sparse:
            dense_score = dense_scores[doc_id]
            sparse_score = sparse_scores[doc_id]
            weighted = dense_weight * dense_score + (1 - dense_weight) * sparse_score
            combined[doc_id] = max(dense_score, sparse_score, weighted)
        elif has_dense:
            combined[doc_id] = dense_scores[doc_id]
        else:
            combined[doc_id] = sparse_scores[doc_id]
    return sorted(combined.items(), key=lambda item: (-item[1], item[0]))[:k]


async def _ready_chunks(
    session: AsyncSession, owner_user_id: uuid.UUID
) -> list[tuple[ChunkRecord, Document]]:
    rows = await session.execute(
        select(ChunkRecord, Document)
        .join(Document, Document.id == ChunkRecord.document_id)
        .where(Document.user_id == owner_user_id, Document.status == READY)
    )
    return [(chunk, document) for chunk, document in rows.all()]


def _to_retrieved(chunk: ChunkRecord, document: Document, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(chunk.id),
        source=document.filename,
        section=chunk.section,
        text=chunk.content,
        parent_text=(chunk.chunk_metadata or {}).get("parent_text"),
        score=score,
    )


async def hybrid_retrieve(
    query: str,
    *,
    session: AsyncSession,
    store: QdrantStore,
    embedder: Embedder,
    owner_user_id: uuid.UUID,
    k: int = 5,
    dense_weight: float = 0.7,
) -> list[RetrievedChunk]:
    """Dense (Qdrant) + sparse (BM25) retrieval, hydrated from Postgres.

    Postgres is the source of truth: hits whose document is not ready or whose chunk
    row is missing are dropped, so stale or orphaned vectors never reach the model.
    """
    ready = await _ready_chunks(session, owner_user_id)
    by_id = {str(chunk.id): (chunk, document) for chunk, document in ready}
    by_point = {
        chunk.qdrant_point_id: str(chunk.id)
        for chunk, _ in ready
        if chunk.qdrant_point_id
    }

    vector = await embedder.embed_query(query)
    hits = await store.search(vector, owner_user_id, limit=CANDIDATE_POOL)
    dense = [
        (by_point[hit.point_id], max(hit.score, 0.0))
        for hit in hits
        if hit.point_id in by_point
    ]
    sparse = bm25_scores(
        query,
        {
            chunk_id: f"{chunk.section or ''} {chunk.content}"
            for chunk_id, (chunk, _) in by_id.items()
        },
    )[:CANDIDATE_POOL]

    merged = merge_hybrid(dense, sparse, dense_weight, k)
    return [_to_retrieved(*by_id[chunk_id], score) for chunk_id, score in merged]
