# Script Inventory

The skill ships a small set of deterministic Python scripts plus shared utility modules. The README highlights the most-used entrypoints; this page is the full inventory with per-script intent notes for maintainers and power users.

## Start Here

| Script | Best for | Notes |
|---|---|---|
| `build_loop.py` | Production runs from drafts to export. | Orchestrates import-time dedup, plan-driven coverage checks, verify, dedup, and optional export in a single command. |
| `generate.py` | Manual import of canonical drafts. | Use directly when you want fine control over `--source-type`, `--dedup-threshold`, or `--dedup-strategy`. |
| `export.py` | Shape verified records into a trainer-ready file. | Supports `openai`, `huggingface`, `csv`, `jsonl`, `all`, plus `--schema-file` for custom flat columns. |

## Generation Pipeline

| Script | Best for | Notes |
|---|---|---|
| `generate.py` | Turning drafted JSONL into canonical SQLite records. | Marks rows `raw_generated`; honours `--allow-injections` and `--enforce-security-flags` for adversarial corpora. |
| `augment.py` | Diversity transforms across persona, tone, difficulty, and adversarial axes. | Metadata-only variants are marked `rewrite_required` until the agent supplies rewritten content. |
| `build_loop.py` | One-command generate -> coverage -> verify -> dedup -> export. | Reads `--plan-file`; detects per-batch drift and writes live progress to `workspace/build_loop_progress.json`; refuses to run without `--review-file` when the plan sets `require_review_file: true`. |

## Collection

| Script | Best for | Notes |
|---|---|---|
| `collect.py` | Low-level fetch and chunk of URLs, web queries, or local paths. | Output has `status: collected`; drafts must be authored before verification. |
| `research.py` | Native research and evidence pipeline driven by the coverage plan. | Writes `research_plan.json`, `sources.jsonl`, `evidence.jsonl`, `coverage_report.json`. Supports `--backend gpt_researcher` when optional deps are installed. |
| `browser_collect.py` | JS-rendered pages or sites where requests fails. | Requires `pip install -r requirements-browser.txt` and `playwright install chromium`. |
| `grounding.py` | Evidence-anchored grounding score for drafted records. | Stopword-filtered overlap with a 0.20 minimum (Phase 14). |

## Quality

| Script | Best for | Notes |
|---|---|---|
| `verify.py` | Heuristic checks plus optional review-file adjudication. | Applies refusal-anchor, anti-trope, schema, response-length, and grounding gates. |
| `dedup.py` | Final near-duplicate removal. | `--strategy {shingle,tfidf,minhash,code}` and `--dedup-on instruction` for prompt-only dedup (Phase 14). |
| `coverage.py` | Bucket, joint-bucket, and provenance coverage measurement. | Use after every batch to find missing buckets before drafting the next batch. |
| `audit.py` | Corpus-level audit across the train/test splits. | Checks split disjointness, taxonomy coverage, source diversity, label balance, synthetic fingerprint, cluster-fallback rate, and context leakage. |
| `quality_report.py` | Corpus-level quality summary. | Emits `workspace/QUALITY_REPORT.json` with response length, structure, and prefix-repetition stats. |
| `review_batch.py` | Build a host-agent review prompt and adjudicate the resulting `review.jsonl`. | Used when semantic LLM judging is required without calling external LLM APIs from local scripts. |

## Agent Observability

| Script | Best for | Notes |
|---|---|---|
| `status.py` | Single-shot corpus snapshot. | Reports effective count, target gap, status breakdown, real-world ratio, top fail reasons, and bucket fills/gaps. |
| `draft_self_check.py` | Pre-import draft linting. | Deterministic checks against seed-generator rules: multi-constraint, trope opener, missing metadata, DPO specifics. |
| `judge_insights.py` | Cluster `fail_reasons` from a review file. | Fully deterministic substring matching into 10 canonical buckets; emits counts, examples, and actionable recommendations. |
| `record_history.py` | Append a lineage snapshot of the DB to a JSONL log. | Records status counts, task-type breakdown, and effective count at a point in time for between-batch tracking. |

## Export

| Script | Best for | Notes |
|---|---|---|
| `export.py` | Train/test split into preset or custom flat schemas plus the data card. | Honours `model_visibility` rules in the coverage plan to sanitize model-visible `instruction` and `context`. |

## Utility modules (`scripts/utils/`)

| Module | What it does |
|---|---|
| `canonical.py` | Canonical record builders, dot-path accessors, and record normalization. |
| `db.py` | Owns the resumable SQLite state model (`workspace/run_state.sqlite` and per-build databases). |
| `schema.py` | JSON Schema validation against `resources/internal-schema/canonical_schema.json`. |
| `files.py` | JSONL/CSV streaming helpers with control-character sanitization. |
| `similarity.py` | Backend implementations of shingle, TF-IDF, and MinHash near-duplicate detectors. |
| `coverage_plan.py` | Loads and validates coverage plans, including joint-bucket and provenance rules. |
| `security.py` | Prompt-injection detection, control-character stripping, and security-flag attachment. |
| `source_dedup.py` | Duplicate detection across collected source chunks. |
| `source_quality.py` | Per-source quality scoring (domain reputation, length, readability). |
| `web.py` | HTTP fetch, content-type filtering, byte-cap and per-domain rate-limit helpers. |
| `research_plan.py` | Loads research plans, manages per-domain caps, and tracks evidence completeness. |
| `visibility.py` | Applies `model_visibility` sanitization rules at export time. |
| `code_quality.py` | AST-aware Python checks plus JSON parsing and JS/shell/SQL delimiter checks. |
| `dpo_quality.py` | DPO-pair gates including chosen/rejected length skew and refusal-in-rejected detection. |
| `benchmark_guard.py` | Public-benchmark fingerprint guardrail to block accidental contamination. |

19 pipeline scripts + 15 utility modules in `scripts/utils/`.
