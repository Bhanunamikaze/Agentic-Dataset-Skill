# Command Reference

Use these commands inside an agent that has the skill installed. The skill also routes natural-language requests directly — explicit `dataset <subcommand>` syntax is optional.

## Command Surface

| Command | What it does | Key flags | Primary output |
|---|---|---|---|
| `dataset generate "<request>"` | Strategy + seed + batch build loop to produce a new dataset. Defaults to `500` records when no size is given. | `--count <n>` | `workspace/canonical_train.jsonl`, `workspace/canonical_test.jsonl`, `DATA_CARD.md` |
| `dataset collect "<topic or query>"` | Fetches source material from URLs, web search, or local files for the agent to draft canonical records from. | `--urls <url1> <url2>`, `--paths <dir>`, `--max-results <n>` (default `10`), `--tool-context <codex\|claude\|antigravity>` | `workspace/collected_<timestamp>.jsonl` |
| `dataset verify <path>` | Imports a file, runs heuristic checks, optional review-file adjudication, dedup, and re-exports. | `--review-file <review.jsonl>`, `--plan-file <coverage_plan.json>`, `--allow-injections`, `--enforce-security-flags` | `workspace/canonical_train.jsonl`, `verified_pass` records in SQLite |
| `dataset audit [<path>]` | Three-phase quality assessment: record-level checks, corpus-level disjointness/leakage, structured report. | (delegates to `verify.py`, `dedup.py`, `export.py`) | `workspace/AUDIT_REPORT.md` |
| `dataset export` | Shapes verified records into a fixed preset or custom flat schema. | `--format <openai\|huggingface\|csv\|jsonl\|all>`, `--schema-file <path>`, `--split <0.0-0.5>`, `--plan-file <coverage_plan.json>` | Train/test files in the requested shape, plus optional `DATA_CARD.md` |

## Natural-Language Routing

You do not need explicit flags. The skill's orchestration layer routes natural-language intent to the right sub-skill and script. Some patterns:

| You type... | Scope | Route |
|---|---|---|
| `Generate a medical triage dataset` | topic-driven generation | strategy → seed → build_loop → export |
| `Generate a 2000-example customer support dataset in OpenAI JSONL` | sized SFT generation | strategy → seed → build_loop → export (`--format openai`) |
| `Turn these URLs into a training dataset` | URL/reference structuring | strategy → collect → seed → build_loop → export |
| `Use web research to build a fintech FAQ dataset` | internet-research generation | research-planner → research → seed → build_loop → export |
| `Normalize this CSV into OpenAI JSONL` | existing-dataset normalization | strategy → seed → verify → export |
| `Verify and score this dataset.jsonl` | verify-only audit | data-verifier → verify → dedup → export |
| `Audit this dataset for leakage and synthetic patterns` | corpus audit | dataset-auditor → audit |
| `Export the verified set with custom headers` | export shaping | formatter-exporter → export |
| `Generate a DPO dataset for Python code review` | DPO generation | strategy → dpo-pair-generator → verify → export |
| `Generate red-team prompt-injection training data` | adversarial corpus | strategy → seed → generate (`--allow-injections`) → verify |

Default size rule: if the user does not specify a target count, `dataset generate` targets `500` records. If they explicitly ask for a sample or prototype, smaller results are acceptable.

## Coverage Plan Keys

Coverage plans steer the build loop, verification, and export gates. They live in `workspace/coverage_plan.json` (or any path passed via `--plan-file`).

| Key | Purpose |
|---|---|
| `target_effective_count` | Required post-dedup record count. The build loop is not done until this is reached. |
| `group_minimums` | Single-axis bucket minimums keyed by metadata paths such as `metadata.subtopic`, `metadata.context_type`, `metadata.response_shape`, or `metadata.label`. |
| `max_share_per_group` | Mode-collapse ceiling for a single bucket. |
| `joint_group_rules` | Multi-axis rules with `fields`, optional `minimums`, and optional `max_share`. Useful for `difficulty x label` or `persona x response_shape`. |
| `required_fields` | Metadata or provenance paths every kept record must carry, e.g. `metadata.evidence_ids`, `metadata.reference_urls`. |
| `provenance` | Real-world grounding gate. Supports `minimum_real_world_share` and required `reference_fields`. |
| `response_length` | Caps median answer size and the share of oversized responses. |
| `response_structure` | Prevents one dominant JSON or text skeleton from taking over the corpus. |
| `response_prefix` | Repeated-opening cap using `prefix_length` and `max_share`. |
| `model_visibility` | Export-time sanitization rules for model-visible `instruction` and `context` (line-prefix removal, answer-bearing line drop, value redaction). Omit to apply a conservative built-in profile; set `"enabled": false` to disable. |
| `require_review_file` | When `true`, `build_loop.py` refuses to run without `--review-file`. |
| `class_balance` | Optional class-share targets for classification corpora. |
| `dpo` | DPO contrastive gates such as `min_pair_count` and `forbid_refusal_in_rejected`. |
| `review_requirements` | Structured review thresholds such as `min_capability_delta_score` and `require_grounding_pass`. |
| `research` | Research/evidence gates including `max_sources_per_domain`, `min_evidence_per_record`, and allowed source domains. |
| `grounding` | Grounding overlap thresholds enforced by `scripts/grounding.py` against `evidence.jsonl`. |

Advanced sections (`provenance`, `response_length`, `response_structure`, `response_prefix`) are warn-only by default. Set `blocking: true` inside a section to make it fail the build.

## Generic Requests

When the user types something like:

```text
generate a 1000-example customer support dataset
```

Treat it as a sized SFT generation request and produce:

- `workspace/canonical_train.jsonl`
- `workspace/canonical_test.jsonl`
- `workspace/DATA_CARD.md`

When the user types:

```text
audit this dataset
```

Treat it as a corpus-level quality assessment and produce:

- `workspace/AUDIT_REPORT.md`

For deeper command guidance, see [[Generation Workflow]] and [[Datasets and Exports]].

## Script Reference

### `judge_insights.py`

Clusters `fail_reasons` from a `review.jsonl` LLM-judge output file and produces a structured JSON summary of failure patterns with actionable recommendations.

| Flag | Required | Default | Description |
|---|---|---|---|
| `--review-file PATH` | yes | — | Path to the `review.jsonl` produced by the LLM judge. |
| `--output PATH` | no | stdout | Write JSON summary to a file instead of stdout. |
| `--top-n INT` | no | `10` | Maximum number of failure-pattern buckets to include. |

**Output shape:**

```json
{
  "total": 100,
  "pass_count": 70,
  "fail_count": 30,
  "pass_rate": 0.70,
  "top_failure_patterns": [
    {"bucket": "vague_instruction", "count": 12, "examples": ["instruction too vague", "ambiguous prompt"]}
  ],
  "recommendations": [
    "12 records failed vague_instruction — tighten instruction specificity in seed-generator prompts"
  ]
}
```

**Canonical buckets:** `vague_instruction`, `weak_response`, `apology_opener`, `trope_opener`, `refusal_error`, `grounding_fail`, `dpo_quality`, `format_violation`, `leakage`, `other`.

Classification is fully deterministic substring matching — no external LLM calls.

**Example usage:**

```bash
python3 scripts/judge_insights.py --review-file workspace/review.jsonl
python3 scripts/judge_insights.py --review-file workspace/review.jsonl --output workspace/judge_insights.json --top-n 5
```

### `build_loop.py` — drift detection and live progress

As of Phase 15, `build_loop.py` adds two new outputs on every run:

**Per-batch drift field** — each entry in `batches_processed` now includes a `drift` object:

```json
{
  "drift_score": 0.12,
  "drift_flag": true,
  "pass_rate_delta": -0.08,
  "gap_count_delta": 2,
  "new_gaps": ["difficulty=hard"],
  "resolved_gaps": ["domain=finance"]
}
```

`drift_flag: true` means the pass rate or gap count shifted enough between batches to warrant inspection before sending the next batch. A `drift_score > 0.10` triggers the flag.

**Live progress file** — written to `workspace/build_loop_progress.json` on every batch boundary (including at session start and end):

```json
{
  "session_id": "build_abc123",
  "batches_total": 5,
  "batches_done": 2,
  "last_batch_path": "workspace/drafts_batch_02.jsonl",
  "last_coverage": { "...": "..." },
  "last_drift": { "drift_score": 0.04, "drift_flag": false },
  "complete": false,
  "timestamp": "2026-05-16T12:34:56"
}
```

Read this file between batches to track progress without waiting for the full build to finish.

### `record_history.py`

Appends a lineage snapshot of the current database state to a JSONL log. Call it between batches to track corpus evolution over time.

| Flag | Required | Default | Description |
|---|---|---|---|
| `--db PATH` | yes | — | SQLite database path. |
| `--output PATH` | no | `workspace/record_history.jsonl` | Appended JSONL log file. |
| `--note TEXT` | no | `""` | Free-text label for this snapshot. |
| `--source-run-id TEXT` | no | `null` | Associate snapshot with a run ID. |

**Output shape (also printed to stdout):**

```json
{
  "timestamp": "2026-05-16T12:00:00+00:00",
  "db_path": "/path/to/build_loop_abc.sqlite",
  "note": "after batch 2",
  "source_run_id": null,
  "status_counts": {
    "raw_generated": 10,
    "augmented": 5,
    "verified_pass": 80,
    "verified_fail": 12,
    "judge_pending": 3,
    "deduped": 2
  },
  "total_records": 112,
  "effective_count": 83,
  "task_type_counts": {"sft": 70, "dpo": 13}
}
```

**Example usage:**

```bash
python3 scripts/record_history.py --db workspace/build_loop_abc.sqlite --note "after batch 2"
python3 scripts/record_history.py --db workspace/build_loop_abc.sqlite --output workspace/my_history.jsonl
```

### `status.py`

Single-shot corpus snapshot — reads the SQLite database and emits effective count, target gap, status breakdown, coverage gaps, and top fail reasons.

```bash
python3 scripts/status.py --db workspace/build_loop_abc.sqlite [--plan-file resources/templates/production_quality_plan.json]
```

### `draft_self_check.py`

Lints a drafts JSONL file before import against seed-generator rules. Catches trope openers, missing required metadata, instruction fidelity issues, and DPO-specific problems.

```bash
python3 scripts/draft_self_check.py --input workspace/drafts_batch_01.jsonl [--plan-file resources/templates/production_quality_plan.json]
```
