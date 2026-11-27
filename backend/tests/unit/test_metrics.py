import json
import logging

import pytest

from app.services.metrics import estimate_cost_usd, log_query_metrics


def test_cost_estimate_uses_per_million_token_prices():
    cost = estimate_cost_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000)

    assert cost == pytest.approx(0.15 + 0.60)


def test_cost_estimate_covers_claude_models():
    haiku = estimate_cost_usd("claude-haiku-4-5", prompt_tokens=2_000, completion_tokens=500)
    sonnet = estimate_cost_usd("claude-sonnet-4-5", prompt_tokens=2_000, completion_tokens=500)

    assert haiku == pytest.approx(2_000 * 1.00e-6 + 500 * 5.00e-6)
    assert sonnet == pytest.approx(2_000 * 3.00e-6 + 500 * 15.00e-6)


def test_cost_estimate_is_zero_without_tokens():
    assert estimate_cost_usd("gpt-4o-mini", prompt_tokens=0, completion_tokens=0) == 0.0


def test_cost_estimate_is_zero_for_unknown_model():
    assert estimate_cost_usd("mystery", prompt_tokens=10, completion_tokens=10) == 0.0


def test_query_metrics_are_logged_as_structured_json(caplog):
    with caplog.at_level(logging.INFO, logger="app.services.metrics"):
        log_query_metrics(
            query_id="q1",
            retrieved_ids=["c1", "c2"],
            scores=[0.9, 0.4],
            latency_ms=12.5,
            prompt_tokens=100,
            completion_tokens=20,
            model="gpt-4o-mini",
        )

    payload = json.loads(caplog.records[0].getMessage())
    assert payload["query_id"] == "q1"
    assert payload["retrieved_ids"] == ["c1", "c2"]
    assert payload["scores"] == [0.9, 0.4]
    assert payload["latency_ms"] == 12.5
    assert payload["token_usage"] == {"prompt_tokens": 100, "completion_tokens": 20}
    assert payload["cost_usd_estimate"] == pytest.approx(100 * 0.15e-6 + 20 * 0.60e-6)
