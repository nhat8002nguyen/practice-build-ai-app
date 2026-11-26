"""Run the golden set against one chunking variant.

    PYTHONPATH=. python -m evals.run_eval [--variant NAME] [--k 3] [--llm none|mock|configured]
"""

import argparse
import asyncio

from app.core.config import settings
from app.services.llm import ConfiguredLLM, LLM

from evals.harness import (
    DEFAULT_K,
    PRODUCTION_VARIANTS,
    VARIANTS,
    EvalReport,
    build_embedder,
    evaluate,
    find_variant,
    load_golden,
)
from evals.mock_llm import MockLLM


def build_eval_llm(name: str) -> LLM | None:
    if name == "none":
        return None
    if name == "mock":
        return MockLLM()
    if name == "configured":
        return ConfiguredLLM()
    raise ValueError(f"Unknown llm {name!r}, choose none, mock or configured")


def format_report(report: EvalReport) -> str:
    cost = f"${report.total_cost_usd:.6f}" if report.generated else "n/a (retrieval only)"
    lines = [
        f"variant: {report.variant} ({report.chunk_count} chunks)",
        f"questions: {len(report.results)}",
        f"hit_rate@{report.k}: {report.hit_rate:.3f}",
        f"recall@{report.k}: {report.recall:.3f}",
        f"refusal_rate: {report.refusal_rate:.3f}",
        f"  correct refusals (should_refuse): {report.correct_refusal_rate:.3f}",
        f"  false refusals (answerable): {report.false_refusal_rate:.3f}",
        f"latency p50: {report.latency_p50_ms:.1f} ms",
        f"latency p95: {report.latency_p95_ms:.1f} ms",
        f"avg context tokens: {report.avg_context_tokens:.0f}",
        f"est. cost: {cost}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--variant",
        default=PRODUCTION_VARIANTS.get(settings.chunk_strategy, "parent_child@128/512"),
        choices=[v.name for v in VARIANTS],
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--embedder", default="hash", choices=["hash", "openai"])
    parser.add_argument("--llm", default="none", choices=["none", "mock", "configured"])
    args = parser.parse_args(argv)

    report = asyncio.run(
        evaluate(
            find_variant(args.variant),
            build_embedder(args.embedder),
            load_golden(),
            k=args.k,
            llm=build_eval_llm(args.llm),
        )
    )
    print(format_report(report))


if __name__ == "__main__":
    main()
