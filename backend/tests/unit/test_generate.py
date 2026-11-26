import asyncio
import json

import pytest

from app.rag.generate import REFUSAL_TEXT, generate_answer
from app.rag.retrieve import RetrievedChunk
from app.services.llm import LLMResult

QUOTE = "Customers may request a full refund within 14 days of purchase."
CHUNK = RetrievedChunk("c1", "policy.md", "Refunds", QUOTE, None, 0.9)


class StubLLM:
    model = "stub"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def complete(self, system, messages) -> LLMResult:
        return LLMResult(json.dumps(self.payload), 10, 5)


def run(answer: str, quote: str):
    llm = StubLLM({"answer": answer, "citations": [{"chunk_id": "c1", "quote": quote}]})
    return asyncio.run(generate_answer("refund?", [CHUNK], [], llm=llm, min_score=0.3))


def test_full_quote_with_grounded_answer_is_accepted():
    answer = run("Refunds are available within 14 days.", QUOTE)

    assert answer.refused is False
    assert answer.citations[0].quote == QUOTE


@pytest.mark.parametrize("quote", ["refund", "full refund", "within 14 days"])
def test_trivial_substring_quotes_are_rejected(quote):
    answer = run("Refunds are available within 14 days.", quote)

    assert answer.refused is True
    assert answer.text == REFUSAL_TEXT
    assert answer.citations == []


def test_invented_figure_is_rejected_even_with_valid_quote():
    answer = run("Refunds are available within 90 days.", QUOTE)

    assert answer.refused is True


def test_quote_of_minimum_length_is_accepted():
    answer = run("A full refund is possible.", "full refund within 14 days")

    assert answer.refused is False
