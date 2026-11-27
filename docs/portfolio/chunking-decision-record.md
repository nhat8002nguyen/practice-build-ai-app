# Chunking decision record

## Question

Which chunking strategy should the knowledge base use by default: `fixed`, `heading`, or `parent_child`?

## Method

The golden set is `backend/evals/golden_set.json`.
Each question lists `relevant_section_substrings`, the phrases a retrieved context must contain to count as evidence.
Refusal questions have no relevant sections and should be declined.

The experiment ingests the fixtures in `backend/evals/fixtures/` through the real ingest pipeline for each chunking variant.
It then runs hybrid retrieval (dense plus BM25) for every golden question.
The context a hit contributes is its parent text when it has one, otherwise the chunk text, because that is what the model reads.

- **hit_rate@k** is the share of answerable questions where at least one relevant substring appears in the top k contexts.
- **recall@k** is the average share of a question's relevant substrings found in the top k contexts.
- **Avg context tokens** is the mean number of whitespace tokens the top k contexts hand to the model, a proxy for prompt cost.
- **Correct refusals** is the share of should-refuse questions that retrieval alone declines (best score below `RETRIEVAL_MIN_SCORE`).
- **False refusals** is the share of answerable questions that retrieval alone declines.

Reproduce and refresh the table below with:

```bash
cd backend
PYTHONPATH=. python -m evals.chunking_experiment
```

Pass `--embedder openai` to use real embeddings (needs `OPENAI_API_KEY`).
Run `PYTHONPATH=. python -m evals.run_eval --variant <name>` for one variant, and add `--llm mock` for a generate pass without an API key.

## Results

<!-- experiment:start -->
Embedder: `hash`, k = 3, 31 golden questions (retrieval only, no LLM).

| Variant | Chunks | hit_rate@3 | recall@3 | Avg context tokens | Correct refusals | False refusals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed@512 | 3 | 1.000 | 1.000 | 559 | 0.500 | 0.080 |
| heading@512 | 17 | 0.880 | 0.880 | 95 | 0.167 | 0.040 |
| parent_child@128/512 | 17 | 0.880 | 0.880 | 95 | 0.167 | 0.040 |
| fixed@48 | 14 | 0.840 | 0.840 | 138 | 0.333 | 0.040 |
| heading@48 | 17 | 0.880 | 0.880 | 95 | 0.167 | 0.040 |
| parent_child@16/64 | 42 | 0.920 | 0.920 | 94 | 0.000 | 0.000 |
<!-- experiment:end -->

## Decision

Keep `parent_child` (128 token children, 512 token parents) as the default `CHUNK_STRATEGY`.
This decision is against the current `HashEmbedder` run (k = 3, 31 questions) after the weighted hybrid merge and `RETRIEVAL_MIN_SCORE=0.3` alignment.
Re-running the script refreshes only the table, so revisit this section when the numbers change.

What the current run shows:

- `fixed@512` scores 1.000 only because each fixture is a single chunk.
  Top 3 then returns most of the knowledge base, at 559 context tokens against 95 for the section-based variants.
  That is a ceiling from tiny documents, not evidence for fixed windows.
- `heading@512`, `heading@48`, and `parent_child@128/512` tie at hit_rate@3 and recall@3 of 0.880 with 95 context tokens and correct refusals of 0.167.
  The fixture sections are shorter than the 128 token child size, so each child is a whole section and `parent_child` behaves exactly like `heading`.
  The run cannot separate these two, and we pick `parent_child` because it carries section metadata for citations like `heading` does, and it splits long sections into precise children that return their parent as context.
  That long-section benefit is untested here.
- `fixed@48` drops to 0.840 at 138 context tokens, because windows cut across section boundaries and carry no section label.
- `parent_child@16/64` reaches hit_rate@3 and recall@3 of 0.920 at 94 context tokens, but correct refusals fall to 0.000.
  Do not shrink the child size below the default to chase lexical hit rate when the retrieval gate can no longer refuse off-topic questions.
- The misses are lexical gaps that `HashEmbedder` cannot bridge, for example "refund money reaches me" against "original payment method" and "cards" against "Visa, Mastercard".
  Real embeddings should help, so re-run with `--embedder openai` before changing any default.

Open item: replace the fixtures with real SMB documents, grow the golden set, and re-run.
Switch strategy only if another variant beats `parent_child@128/512` on recall@k without a large context token increase or a collapse in correct refusals.

## Ownership gate E (Nate)

Answer "How did you choose chunking?" in your own words, citing the hit_rate@k and recall@k numbers from the table above.

## Caveats

- The fixtures are a few hundred words each, so the production 512-token windows turn every document into one chunk.
  The `@48` and `@16/64` variants shrink the windows to stand in for long documents.
- `HashEmbedder` is a bag-of-words hash, so dense retrieval here behaves like a second lexical signal.
  Re-run with `--embedder openai` before trusting differences that depend on semantic matching.
- The golden set is small and written by us.
  Expand it with real SMB documents and questions when they arrive, then re-run and update this record.
