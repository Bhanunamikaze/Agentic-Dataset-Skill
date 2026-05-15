# Generation Workflow

A generation run is a batch-driven loop that progresses canonical records through explicit lifecycle statuses inside a single SQLite database. The agent does the reasoning (strategy, drafting, judging); the bundled scripts do the deterministic work (import, verify, dedup, coverage, export).

## Phases Overview

1. **Strategy** — read `sub-skills/dataset-strategy.md`. Decide `task_type` (`sft` or `dpo`), `source_type` (`generated`, `url_reference`, `raw_dataset`, `internet_research`), target export schema, target effective example count, and whether to resume an existing run.
2. **Seed or collect** — for topic-driven datasets, read `sub-skills/seed-generator.md` and draft canonical JSONL directly. For URL or research-driven datasets, read `sub-skills/local-collector.md` and run `scripts/collect.py` or `scripts/research.py` to gather material first.
3. **Batch build loop** — run `scripts/build_loop.py` with one or more drafted batches and a coverage plan. The loop performs import-time dedup, plan-driven required-field checks, and a coverage measurement after every batch.
4. **Heuristic verification** — `scripts/verify.py` applies refusal-anchor, anti-trope, schema, response-length, and grounding gates. Records become `verified_pass` or `verified_fail`.
5. **Semantic review** — read `sub-skills/llm-judge.md`, produce a `review.jsonl` of capability-delta scores and grounding verdicts, and feed it back through `verify.py --review-file`.
6. **Final deduplication** — `scripts/dedup.py --from-status verified_pass` removes near-duplicates with the configured similarity strategy (`minhash`, `shingle`, `tfidf`, or `code`).
7. **Export and data card** — `scripts/export.py` emits preset or custom-flat outputs plus `DATA_CARD.md`. See [[Datasets and Exports]] for every artifact the pipeline writes.

## State Model

`workspace/run_state.sqlite` (or a per-build `workspace/build_loop_build_<hash>.sqlite`) is owned by `scripts/utils/db.py`. Every pipeline stage reads from and writes to the same DB, so an interrupted run can resume without re-collecting or re-judging records.

Record status progression:

```text
seeded
  -> raw_generated      (after generate.py import)
  -> augmented          (after augment.py rewrites or metadata variants)
  -> judge_pending      (passed heuristics, awaiting semantic review)
  -> verified_pass      (heuristics + optional review accepted)
  -> verified_fail      (heuristics or review rejected)
  -> deduped            (dropped by near-duplicate detection)
```

Records that are scaffolding-only (metadata variants without rewritten content) are marked `rewrite_required` and cannot pass `verify.py` until the agent supplies real instruction/response text. Raw `collected` chunks from `scripts/collect.py` are never valid training examples on their own.

## Coverage Steering

`scripts/coverage.py` runs after every batch import and after every augmentation pass. It compares the current effective record count against the plan and emits a structured gap report.

```bash
python3 scripts/coverage.py \
    --from-status raw_generated \
    --from-status augmented \
    --from-status verified_pass \
    --threshold 0.85 \
    --plan-file workspace/coverage_plan.json
```

The agent uses the gap report to draft the next batch only for missing buckets — for example, by topic, response shape, persona, or difficulty. See [[Command Reference]] for every coverage-plan key.

A run is not complete until both:

- the post-dedup effective count meets `target_effective_count`
- every required bucket in `group_minimums` and `joint_group_rules` meets its minimum

Inflated raw-import counts are not success.

## Quality Gates That Auto-Run

The Phase 14 hardening pass added deterministic gates that run inside `verify.py`, `audit.py`, and `dedup.py` without any opt-in flag:

- **Anti-trope opener** — assistant responses cannot start with templated phrasings (`"As an AI"`, `"Certainly!"`, `"I am happy to help"`). See [[Troubleshooting]] -> `response begins with trope opener`.
- **Refusal-anchored regex** — refusal patterns anchor to the first 200 characters of the response, so legitimate content containing `"I cannot"` mid-sentence is not falsely rejected. Records explicitly labelled as refusal training data (via `metadata.label` or `metadata.intent`) are exempt.
- **DPO chosen-side checks** — the chosen response in a preference pair is run through the same refusal, anti-trope, and grounding checks as standalone records. The preferred side cannot be worse than the rejected side.
- **Context-leakage audit** — `audit.py` walks model-visible fields and flags plan/system text that leaked into `instruction` or `context` during generation.
- **Grounding overlap floor** — `scripts/grounding.py` strips stopwords from evidence comparisons and requires response/evidence overlap to be at least `0.20` of content-bearing tokens.
- **Instruction-only dedup** — `dedup.py --dedup-on instruction` catches prompt repetition independently of response diversity.

Each gate has a matching failure mode in [[Troubleshooting]].

## When the Build Loop Completes

When `build_loop.py` exits with the coverage plan satisfied, the workspace contains the canonical splits, the data card, the audit report, and any preset-format exports requested via `--export-format`. See [[Datasets and Exports]] for the full list of artifacts and how to consume them.
