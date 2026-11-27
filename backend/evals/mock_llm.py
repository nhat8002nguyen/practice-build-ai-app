import json
import re

from app.rag.retrieve import tokenize
from app.services.llm import LLMResult

MIN_SHARED_TERMS = 2
QUOTE_WORDS = 12
_EXCERPT = re.compile(
    r"\[chunk_id=([^\]]+)\] \(source:[^\n]*\)\n(.*?)(?=\n\n\[chunk_id=|\Z)", re.DOTALL
)


class MockLLM:
    """Deterministic stand-in so generate evals run in CI without an API key.

    It quotes the excerpt that shares the most words with the question, and says
    "insufficient evidence" when fewer than two words are shared. It checks the
    plumbing (citations, refusal, token and cost accounting), not answer quality.
    """

    model = "gpt-4o-mini"

    async def complete(self, system: str, messages: list[dict[str, str]]) -> LLMResult:
        question_terms = set(tokenize(messages[-1]["content"]))
        best_id, best_text, best_overlap = "", "", 0
        for chunk_id, excerpt in _EXCERPT.findall(system):
            overlap = len(question_terms & set(tokenize(excerpt)))
            if overlap > best_overlap:
                best_id, best_text, best_overlap = chunk_id, excerpt, overlap

        if best_overlap < MIN_SHARED_TERMS:
            text = json.dumps({"insufficient_evidence": True})
        else:
            quote = " ".join(best_text.split()[:QUOTE_WORDS])
            text = json.dumps(
                {
                    "answer": quote,
                    "citations": [{"chunk_id": best_id, "quote": quote}],
                }
            )
        return LLMResult(text, len(system.split()), len(text.split()))
