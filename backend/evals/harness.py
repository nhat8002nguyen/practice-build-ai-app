import json
import math
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base
from app.models.entities import User
from app.rag.chunking import (
    Chunk,
    chunk_by_heading,
    chunk_fixed,
    chunk_parent_child,
)
from app.rag.embeddings import Embedder, HashEmbedder, OpenAIEmbedder
from app.rag.generate import generate_answer
from app.rag.pipeline import ingest_document
from app.rag.retrieve import RetrievedChunk, hybrid_retrieve
from app.rag.store import QdrantStore
from app.services.llm import LLM
from app.services.metrics import estimate_cost_usd

EVALS_DIR = Path(__file__).parent
GOLDEN_PATH = EVALS_DIR / "golden_set.json"
FIXTURES_DIR = EVALS_DIR / "fixtures"
DEFAULT_K = 3


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    question: str
    relevant_section_substrings: list[str]
    should_refuse: bool


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    questions = [
        GoldenQuestion(
            id=item["id"],
            question=item["question"],
            relevant_section_substrings=list(item["relevant_section_substrings"]),
            should_refuse=bool(item["should_refuse"]),
        )
        for item in json.loads(path.read_text())
    ]
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Golden set has duplicate ids")
    for q in questions:
        if q.should_refuse == bool(q.relevant_section_substrings):
            raise ValueError(
                f"{q.id}: refusal questions have no relevant sections, others need at least one"
            )
    return questions


@dataclass(frozen=True)
class ChunkVariant:
    name: str
    strategy: str
    chunker: Callable[[str], list[Chunk]]


# Fixtures are a few hundred words, so the production 512-token windows turn every
# document into one chunk. The small variants stand in for long real documents.
VARIANTS = [
    ChunkVariant("fixed@512", "fixed", chunk_fixed),
    ChunkVariant("heading@512", "heading", chunk_by_heading),
    ChunkVariant("parent_child@128/512", "parent_child", chunk_parent_child),
    ChunkVariant("fixed@48", "fixed", partial(chunk_fixed, size_tokens=48)),
    ChunkVariant("heading@48", "heading", partial(chunk_by_heading, max_tokens=48)),
    ChunkVariant(
        "parent_child@16/64",
        "parent_child",
        partial(chunk_parent_child, child_tokens=16, parent_tokens=64),
    ),
]
PRODUCTION_VARIANTS = {
    "fixed": "fixed@512",
    "heading": "heading@512",
    "parent_child": "parent_child@128/512",
}


def find_variant(name: str) -> ChunkVariant:
    for variant in VARIANTS:
        if variant.name == name:
            return variant
    raise ValueError(f"Unknown variant {name!r}, choose from {[v.name for v in VARIANTS]}")


def build_embedder(name: str) -> Embedder:
    if name == "hash":
        return HashEmbedder()
    if name == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --embedder openai")
        return OpenAIEmbedder(settings.openai_api_key, settings.embedding_model)
    raise ValueError(f"Unknown embedder {name!r}, choose hash or openai")


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def context_text(chunk: RetrievedChunk) -> str:
    """The text the model would see for this hit: the parent when there is one."""
    return chunk.parent_text or chunk.text


def covered_substrings(substrings: list[str], chunks: list[RetrievedChunk]) -> int:
    context = _squash(" ".join(context_text(c) for c in chunks))
    return sum(1 for s in substrings if _squash(s) in context)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


@dataclass
class QuestionResult:
    question: GoldenQuestion
    chunks: list[RetrievedChunk]
    refused: bool
    latency_ms: float
    cost_usd: float


@dataclass
class EvalReport:
    variant: str
    k: int
    generated: bool
    chunk_count: int
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def _answerable(self) -> list[QuestionResult]:
        return [r for r in self.results if not r.question.should_refuse]

    @property
    def _should_refuse(self) -> list[QuestionResult]:
        return [r for r in self.results if r.question.should_refuse]

    @property
    def hit_rate(self) -> float:
        rows = self._answerable
        hits = sum(
            1
            for r in rows
            if covered_substrings(r.question.relevant_section_substrings, r.chunks)
        )
        return hits / len(rows) if rows else 0.0

    @property
    def recall(self) -> float:
        rows = self._answerable
        if not rows:
            return 0.0
        return sum(
            covered_substrings(r.question.relevant_section_substrings, r.chunks)
            / len(r.question.relevant_section_substrings)
            for r in rows
        ) / len(rows)

    @property
    def refusal_rate(self) -> float:
        return _share(self.results, lambda r: r.refused)

    @property
    def correct_refusal_rate(self) -> float:
        return _share(self._should_refuse, lambda r: r.refused)

    @property
    def false_refusal_rate(self) -> float:
        return _share(self._answerable, lambda r: r.refused)

    @property
    def latency_p50_ms(self) -> float:
        return percentile([r.latency_ms for r in self.results], 0.50)

    @property
    def latency_p95_ms(self) -> float:
        return percentile([r.latency_ms for r in self.results], 0.95)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def avg_context_tokens(self) -> float:
        if not self.results:
            return 0.0
        return sum(
            len(context_text(c).split()) for r in self.results for c in r.chunks
        ) / len(self.results)


def _share(rows: list[QuestionResult], predicate: Callable[[QuestionResult], bool]) -> float:
    return sum(1 for r in rows if predicate(r)) / len(rows) if rows else 0.0


@dataclass
class Index:
    session_factory: async_sessionmaker
    store: QdrantStore
    embedder: Embedder
    owner_user_id: uuid.UUID
    chunk_count: int


@asynccontextmanager
async def build_index(
    variant: ChunkVariant, embedder: Embedder, fixtures_dir: Path = FIXTURES_DIR
) -> AsyncIterator[Index]:
    """Ingests the fixtures through the real pipeline into throwaway SQLite + in-memory Qdrant."""
    with tempfile.TemporaryDirectory() as workdir:
        engine = create_async_engine(f"sqlite+aiosqlite:///{workdir}/eval.db")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        store = QdrantStore(AsyncQdrantClient(":memory:"), "eval_chunks")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            owner = User(email="eval@example.com", password_hash="unused")
            async with session_factory() as session:
                session.add(owner)
                await session.commit()
                chunk_count = 0
                for path in sorted(fixtures_dir.glob("*.md")):
                    _, records = await ingest_document(
                        session,
                        store,
                        embedder,
                        owner_user_id=owner.id,
                        filename=path.name,
                        source_type="upload",
                        source_uri=None,
                        text=path.read_text(),
                        strategy=variant.strategy,
                        chunker=variant.chunker,
                    )
                    chunk_count += len(records)
            yield Index(session_factory, store, embedder, owner.id, chunk_count)
        finally:
            await engine.dispose()


async def _run_question(
    index: Index, question: GoldenQuestion, k: int, llm: LLM | None
) -> QuestionResult:
    started = time.perf_counter()
    async with index.session_factory() as session:
        chunks = await hybrid_retrieve(
            question.question,
            session=session,
            store=index.store,
            embedder=index.embedder,
            owner_user_id=index.owner_user_id,
            k=k,
            dense_weight=settings.retrieval_dense_weight,
        )
    cost = 0.0
    if llm is None:
        refused = not chunks or max(c.score for c in chunks) < settings.retrieval_min_score
    else:
        answer = await generate_answer(question.question, chunks, [], llm=llm)
        refused = answer.refused
        cost = estimate_cost_usd(
            llm.model, answer.usage.prompt_tokens, answer.usage.completion_tokens
        )
    latency_ms = (time.perf_counter() - started) * 1000
    return QuestionResult(question, chunks, refused, latency_ms, cost)


async def evaluate(
    variant: ChunkVariant,
    embedder: Embedder,
    golden: list[GoldenQuestion],
    *,
    k: int = DEFAULT_K,
    llm: LLM | None = None,
    fixtures_dir: Path = FIXTURES_DIR,
) -> EvalReport:
    async with build_index(variant, embedder, fixtures_dir) as index:
        report = EvalReport(variant.name, k, llm is not None, index.chunk_count)
        for question in golden:
            report.results.append(await _run_question(index, question, k, llm))
    return report
