"""Compare chunking variants on the golden set and write the table into the decision record.

    PYTHONPATH=. python -m evals.chunking_experiment [--embedder hash|openai] [--k 3]
"""

import argparse
import asyncio
from pathlib import Path

from evals.harness import (
    DEFAULT_K,
    VARIANTS,
    EvalReport,
    build_embedder,
    evaluate,
    load_golden,
)

DECISION_RECORD = (
    Path(__file__).resolve().parents[2] / "docs/portfolio/chunking-decision-record.md"
)
START_MARKER = "<!-- experiment:start -->"
END_MARKER = "<!-- experiment:end -->"


def format_table(reports: list[EvalReport], embedder: str, question_count: int) -> str:
    k = reports[0].k
    header = (
        f"Embedder: `{embedder}`, k = {k}, {question_count} golden questions "
        "(retrieval only, no LLM).\n\n"
        f"| Variant | Chunks | hit_rate@{k} | recall@{k} | Avg context tokens "
        "| Correct refusals | False refusals |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    )
    rows = [
        f"| {r.variant} | {r.chunk_count} | {r.hit_rate:.3f} | {r.recall:.3f} "
        f"| {r.avg_context_tokens:.0f} | {r.correct_refusal_rate:.3f} "
        f"| {r.false_refusal_rate:.3f} |"
        for r in reports
    ]
    return "\n".join([header, *rows])


def replace_table(document: str, table: str) -> str:
    start = document.find(START_MARKER)
    end = document.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Decision record must contain {START_MARKER} and {END_MARKER}")
    return f"{document[: start + len(START_MARKER)]}\n{table}\n{document[end:]}"


async def run_experiment(embedder_name: str, k: int) -> tuple[list[EvalReport], int]:
    golden = load_golden()
    embedder = build_embedder(embedder_name)
    reports = [await evaluate(variant, embedder, golden, k=k) for variant in VARIANTS]
    return reports, len(golden)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedder", default="hash", choices=["hash", "openai"])
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--output", type=Path, default=DECISION_RECORD)
    args = parser.parse_args(argv)

    reports, question_count = asyncio.run(run_experiment(args.embedder, args.k))
    table = format_table(reports, args.embedder, question_count)
    print(table)
    args.output.write_text(replace_table(args.output.read_text(), table))
    print(f"\nUpdated {args.output}")


if __name__ == "__main__":
    main()
