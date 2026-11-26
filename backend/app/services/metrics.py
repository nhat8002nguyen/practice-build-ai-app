import json
import logging

logger = logging.getLogger(__name__)

# USD per 1M tokens: (prompt, completion)
_PRICES_PER_MILLION = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_price, completion_price = _PRICES_PER_MILLION.get(model, (0.0, 0.0))
    return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000


def log_query_metrics(
    *,
    query_id: str,
    retrieved_ids: list[str],
    scores: list[float],
    latency_ms: float,
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> None:
    logger.info(
        json.dumps(
            {
                "query_id": query_id,
                "retrieved_ids": retrieved_ids,
                "scores": scores,
                "latency_ms": latency_ms,
                "token_usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
                "cost_usd_estimate": estimate_cost_usd(
                    model, prompt_tokens, completion_tokens
                ),
            }
        )
    )
