import asyncio
import json

import pytest

from app.rag.retrieve import RetrievedChunk
from evals import chunking_experiment, run_eval
from evals.harness import (
    PRODUCTION_VARIANTS,
    VARIANTS,
    EvalReport,
    GoldenQuestion,
    HashEmbedder,
    QuestionResult,
    covered_substrings,
    evaluate,
    find_variant,
    load_golden,
    percentile,
)
from evals.mock_llm import MockLLM


def chunk(text: str, parent_text: str | None = None, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk("id", "doc.md", None, text, parent_text, score)


def result(
    question: GoldenQuestion, chunks: list[RetrievedChunk], refused: bool = False
) -> QuestionResult:
    return QuestionResult(question, chunks, refused, latency_ms=10.0, cost_usd=0.0)


def answerable(*substrings: str) -> GoldenQuestion:
    return GoldenQuestion("q", "question", list(substrings), False)


def test_golden_set_follows_the_schema():
    golden = load_golden()

    assert 20 <= len(golden) <= 40
    assert any(q.should_refuse for q in golden)
    assert any(len(q.relevant_section_substrings) > 1 for q in golden)


def test_golden_substrings_exist_in_the_fixtures():
    from evals.harness import FIXTURES_DIR

    corpus = " ".join(
        " ".join(path.read_text().lower().split()) for path in FIXTURES_DIR.glob("*.md")
    )
    for question in load_golden():
        for substring in question.relevant_section_substrings:
            assert " ".join(substring.lower().split()) in corpus, question.id


def test_golden_loader_rejects_inconsistent_refusal_rows(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            [{"id": "a", "question": "q", "relevant_section_substrings": [], "should_refuse": False}]
        )
    )

    with pytest.raises(ValueError, match="refusal questions"):
        load_golden(path)


def test_covered_substrings_read_the_parent_context_and_ignore_case_and_spacing():
    hit = chunk("child", parent_text="The Refund   window\nis 14 days")

    assert covered_substrings(["refund window is 14 days", "missing"], [hit]) == 1


def test_percentile_uses_nearest_rank():
    values = [float(n) for n in range(1, 101)]

    assert percentile(values, 0.50) == 50.0
    assert percentile(values, 0.95) == 95.0
    assert percentile([], 0.5) == 0.0


def test_report_metrics_on_known_results():
    hit = answerable("alpha")
    partial = answerable("alpha", "beta")
    miss = answerable("gamma")
    refuse_ok = GoldenQuestion("r1", "q", [], True)
    refuse_bad = GoldenQuestion("r2", "q", [], True)
    report = EvalReport(
        "v",
        3,
        False,
        5,
        [
            result(hit, [chunk("alpha")]),
            result(partial, [chunk("alpha")]),
            result(miss, [chunk("alpha")], refused=True),
            result(refuse_ok, [], refused=True),
            result(refuse_bad, [chunk("alpha beta")]),
        ],
    )

    assert report.hit_rate == pytest.approx(2 / 3)
    assert report.recall == pytest.approx((1 + 0.5 + 0) / 3)
    assert report.refusal_rate == pytest.approx(2 / 5)
    assert report.correct_refusal_rate == pytest.approx(1 / 2)
    assert report.false_refusal_rate == pytest.approx(1 / 3)
    assert report.avg_context_tokens == pytest.approx((1 + 1 + 1 + 0 + 2) / 5)


def test_retrieval_eval_finds_the_refund_policy():
    golden = [q for q in load_golden() if q.id in {"refund-window", "off-topic-sports"}]

    report = asyncio.run(
        evaluate(find_variant(PRODUCTION_VARIANTS["parent_child"]), HashEmbedder(), golden)
    )

    assert report.hit_rate == 1.0
    assert report.correct_refusal_rate == 1.0
    assert report.total_cost_usd == 0.0


def test_generate_eval_with_mock_llm_cites_and_costs():
    golden = [q for q in load_golden() if q.id in {"refund-window", "off-topic-sports"}]

    report = asyncio.run(
        evaluate(
            find_variant(PRODUCTION_VARIANTS["heading"]),
            HashEmbedder(),
            golden,
            llm=MockLLM(),
        )
    )

    by_id = {r.question.id: r for r in report.results}
    assert by_id["refund-window"].refused is False
    assert by_id["off-topic-sports"].refused is True
    assert report.total_cost_usd > 0


def test_every_variant_runs_and_production_variants_exist():
    golden = load_golden()[:3]

    for variant in VARIANTS:
        report = asyncio.run(evaluate(variant, HashEmbedder(), golden))
        assert report.chunk_count > 0
    assert set(PRODUCTION_VARIANTS.values()) <= {v.name for v in VARIANTS}


def test_run_eval_cli_prints_the_required_metrics(capsys):
    run_eval.main(["--llm", "mock", "--k", "2"])

    output = capsys.readouterr().out
    for label in ("hit_rate@2", "recall@2", "refusal_rate", "latency p50", "latency p95", "est. cost"):
        assert label in output


def test_experiment_replaces_only_the_table_between_markers(tmp_path):
    record = tmp_path / "record.md"
    record.write_text(
        "intro\n<!-- experiment:start -->\nold\n<!-- experiment:end -->\noutro\n"
    )

    chunking_experiment.main(["--output", str(record), "--k", "2"])

    text = record.read_text()
    assert text.startswith("intro\n<!-- experiment:start -->\n")
    assert text.endswith("<!-- experiment:end -->\noutro\n")
    assert "\nold\n" not in text
    assert "hit_rate@2" in text
    for variant in VARIANTS:
        assert f"| {variant.name} |" in text


def test_experiment_requires_markers_in_the_decision_record():
    with pytest.raises(ValueError, match="experiment:start"):
        chunking_experiment.replace_table("no markers here", "table")


def test_format_table_reports_variant_metrics_from_evaluate():
    golden = load_golden()[:3]
    reports = [
        asyncio.run(evaluate(variant, HashEmbedder(), golden, k=2)) for variant in VARIANTS
    ]

    table = chunking_experiment.format_table(reports, "hash", len(golden))

    assert "hit_rate@2" in table
    assert "Embedder: `hash`" in table
    for report in reports:
        assert report.chunk_count > 0
        assert f"| {report.variant} |" in table
        assert f"| {report.hit_rate:.3f} |" in table
        assert f"| {report.correct_refusal_rate:.3f} |" in table
