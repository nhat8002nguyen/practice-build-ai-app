import pytest

from app.rag.retrieve import bm25_scores, merge_hybrid


def test_hybrid_merge_prefers_agreement():
    dense = [("a", 0.9), ("b", 0.2)]
    sparse = [("a", 0.8), ("c", 0.7)]

    merged = merge_hybrid(dense, sparse, dense_weight=0.7, k=2)

    assert merged[0][0] == "a"
    assert merged[0][1] == pytest.approx(0.7 * 0.9 + 0.3 * 0.8)
    assert len(merged) == 2


def test_hybrid_merge_weight_shifts_ranking():
    dense = [("a", 0.9), ("b", 0.4)]
    sparse = [("a", 0.4), ("b", 0.9)]

    assert merge_hybrid(dense, sparse, dense_weight=0.8, k=1)[0][0] == "a"
    assert merge_hybrid(dense, sparse, dense_weight=0.2, k=1)[0][0] == "b"


def test_hybrid_merge_handles_empty_inputs():
    assert merge_hybrid([], [], dense_weight=0.7, k=5) == []
    assert merge_hybrid([("a", 0.5)], [], dense_weight=0.7, k=5) == [("a", pytest.approx(0.5))]


def test_hybrid_merge_single_channel_perfect_match_scores_one():
    sparse_only = merge_hybrid([], [("sku", 1.0)], dense_weight=0.7, k=1)
    dense_only = merge_hybrid([("sku", 1.0)], [], dense_weight=0.7, k=1)

    assert sparse_only == [("sku", pytest.approx(1.0))]
    assert dense_only == [("sku", pytest.approx(1.0))]
    assert sparse_only[0][1] >= 0.35
    assert dense_only[0][1] >= 0.35


def test_bm25_ranks_matching_document_first_and_normalizes_to_one():
    documents = {
        "refund": "customers may request a full refund within 14 days",
        "shipping": "orders ship within 2 business days",
    }

    scores = bm25_scores("refund policy", documents)

    assert scores[0] == ("refund", 1.0)
    assert all(doc_id != "shipping" for doc_id, _ in scores)


def test_bm25_ignores_stopword_only_queries():
    assert bm25_scores("what is the", {"a": "what is the plan"}) == []
