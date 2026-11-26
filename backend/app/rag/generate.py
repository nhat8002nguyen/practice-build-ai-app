import json
import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.rag.retrieve import RetrievedChunk
from app.services.llm import LLM

MIN_QUOTE_CHARS = 20
MIN_QUOTE_WORDS = 4
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

REFUSAL_TEXT = "I don't know based on the knowledge base."

SYSTEM_PROMPT = """You are a support assistant. Answer ONLY from the knowledge base excerpts below.
Never invent policy, prices, dates, or procedures that are not in the excerpts.
Reply with a JSON object:
{"answer": "<answer text>", "citations": [{"chunk_id": "<id>", "quote": "<exact words copied from that excerpt>"}]}
Every claim must be backed by at least one citation, and each quote must be copied verbatim from the cited excerpt.
If the excerpts do not contain enough evidence, reply {"insufficient_evidence": true}.

Knowledge base excerpts:
"""


@dataclass
class Citation:
    chunk_id: str
    source: str
    quote: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    refused: bool = False
    usage: Usage = field(default_factory=Usage)


def _refusal(usage: Usage | None = None) -> Answer:
    return Answer(REFUSAL_TEXT, [], True, usage or Usage())


def _build_system_prompt(chunks: list[RetrievedChunk]) -> str:
    excerpts = [
        f"[chunk_id={c.chunk_id}] (source: {c.source}"
        f"{', section: ' + c.section if c.section else ''})\n{c.parent_text or c.text}"
        for c in chunks
    ]
    return SYSTEM_PROMPT + "\n\n".join(excerpts)


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _is_substantial(quote: str) -> bool:
    return len(quote) >= MIN_QUOTE_CHARS and len(quote.split()) >= MIN_QUOTE_WORDS


def _verified_citations(raw: object, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Keep only citations that point at a retrieved chunk and quote it verbatim.

    Quotes must be substantial: a one-word match like "refund" proves nothing.
    """
    by_id = {c.chunk_id: c for c in chunks}
    citations: list[Citation] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        chunk = by_id.get(str(item.get("chunk_id")))
        quote = str(item.get("quote") or "").strip()
        if chunk is None or not _is_substantial(quote):
            continue
        evidence = _squash(f"{chunk.text} {chunk.parent_text or ''}")
        if _squash(quote) in evidence:
            citations.append(Citation(chunk.chunk_id, chunk.source, quote))
    return citations


def _numbers_are_grounded(
    text: str, citations: list[Citation], chunks: list[RetrievedChunk]
) -> bool:
    """Every figure in the answer (days, prices, limits) must appear in a cited chunk."""
    cited = {c.chunk_id for c in citations}
    evidence = " ".join(
        f"{c.text} {c.parent_text or ''}" for c in chunks if c.chunk_id in cited
    )
    available = set(_NUMBER.findall(evidence))
    return all(number in available for number in _NUMBER.findall(text))


async def generate_answer(
    query: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]],
    *,
    llm: LLM,
    min_score: float | None = None,
) -> Answer:
    threshold = settings.retrieval_min_score if min_score is None else min_score
    if not chunks or max(c.score for c in chunks) < threshold:
        return _refusal()

    result = await llm.complete(
        _build_system_prompt(chunks), [*history, {"role": "user", "content": query}]
    )
    usage = Usage(result.prompt_tokens, result.completion_tokens)
    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError:
        return _refusal(usage)
    if not isinstance(parsed, dict) or parsed.get("insufficient_evidence"):
        return _refusal(usage)

    text = str(parsed.get("answer") or "").strip()
    citations = _verified_citations(parsed.get("citations"), chunks)
    grounded = bool(citations) and _numbers_are_grounded(text, citations, chunks)
    if not text or not grounded:
        return _refusal(usage)
    return Answer(text, citations, False, usage)
