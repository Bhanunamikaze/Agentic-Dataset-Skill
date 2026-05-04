# Workflow Notes

## Collect Flow

Use this when the user wants source material fetched before drafting training records.

1. **First**: try the IDE's native search/browsing tools to collect material.
2. **Fallback**: run `scripts/collect.py` for large collections or when IDE tools are unavailable:
   ```bash
   # Web search
   python3 scripts/collect.py --query "<topic>" --max-results 10 --tool-context codex
   # Explicit URLs
   python3 scripts/collect.py --urls <url1> [url2 ...] --tool-context codex
   # Local files / repos
   python3 scripts/collect.py --paths ./docs ./README.md --tool-context codex
   ```
3. The collector writes `workspace/collected_<timestamp>.jsonl` (records with `status: collected`).
4. Read the collected JSONL and draft canonical instruction/response records.
5. Import the drafts into the pipeline:
   ```bash
   python3 scripts/generate.py --input workspace/drafts.jsonl \
       --source-type url_reference --tool-context codex
   ```
6. Continue with the standard verify → dedup → export pipeline.

## Generate Flow

Use this when the user wants a new dataset or wants raw material turned into one.

1. decide request type, `task_type` (`sft` vs `dpo`), `source_type`, and target schema
2. set the target **effective** example count and coverage minima
3. if the user does not specify a size, default to `500`
4. generate or collect records in batches instead of one monolithic pass
5. inspect recent runs in SQLite
6. collect or write canonical draft records with coverage metadata
7. prefer `scripts/build_loop.py` to orchestrate import, verify, incremental dedup, and coverage checks
8. if running manually, import drafts with `scripts/generate.py --dedup-threshold 0.85`
9. if running manually, run `scripts/coverage.py` to measure effective count, bucket gaps, joint-bucket skew, provenance, and response-prefix repetition
10. repeat steps 6–9 until the coverage plan is satisfied
11. augment if needed
12. generate preference pairs using `dpo-pair-generator` if `task_type` is `dpo`
13. verify
14. deduplicate
15. export

Recommended automated loop:

```bash
python3 scripts/build_loop.py \
    --batch workspace/drafts_batch_01.jsonl \
    --batch workspace/drafts_batch_02.jsonl \
    --plan-file workspace/coverage_plan.json \
    --source-type generated \
    --tool-context codex \
    --review-file workspace/review.jsonl \
    --verify-min-response-length 5
```

For label-only classification datasets such as `VULNERABLE` / `NOT_VULNERABLE`, lower `--verify-min-response-length` so short labels are not incorrectly rejected by the generic heuristic.
If the plan sets `require_review_file: true`, `build_loop.py` requires `--review-file` so semantic judging happens during the build.

Equivalent manual generation-time coverage loop:

```bash
python3 scripts/generate.py --input workspace/drafts_batch_01.jsonl \
    --source-type generated --tool-context codex --dedup-threshold 0.85

python3 scripts/coverage.py \
    --from-status raw_generated \
    --from-status augmented \
    --from-status verified_pass \
    --threshold 0.85 \
    --plan-file workspace/coverage_plan.json
```

Treat the run as incomplete until both conditions are true:
- effective count meets the planned target
- every required bucket in the coverage plan meets its minimum

For higher-signal datasets, also treat the run as incomplete until:
- required fields are present on every effective record
- provenance rules are satisfied
- joint-bucket mode collapse is below the configured threshold
- repeated response openings stay below the configured prefix cap

If you do not provide a `review-file`, the loop can still steer coverage and filter heuristics, but the records remain `judge_pending` rather than fully validated `verified_pass`.

Generic plan fields now supported by `scripts/coverage.py` and `scripts/verify.py`:

- `required_fields`
- `group_minimums`
- `max_share_per_group`
- `joint_group_rules`
- `provenance`
- `response_length`
- `response_structure`
- `response_prefix`
- `model_visibility`
- `require_review_file`

Advanced quality sections are warn-only by default. Add `blocking: true` inside `provenance`, `response_length`, `response_structure`, or `response_prefix` only when you want that specific issue to prevent completion.

When the dataset keeps answer-bearing metadata for audit or analytics but the model should not see those values verbatim, define `model_visibility` in the plan. `scripts/export.py` and `scripts/build_loop.py --export-format ...` will apply those rules to exported `instruction` and `context` fields while leaving metadata intact. If `model_visibility` is omitted, export now applies a conservative built-in profile by default; set `"enabled": false` to disable it for a raw export.

## Audit & Verify Flow

Use this when the user already has a dataset (or just generated one) and wants a structured quality assessment.

1. import the file with `scripts/generate.py --source-type raw_dataset` (if not already generated)
2. capture the generated `run_id`
3. If running **Verify** (fast heuristic checks):
   - run `scripts/verify.py --source-run-id <run_id>`
   - run `scripts/dedup.py --source-run-id <run_id>`
   - export audit-ready outputs
4. If running **Audit** (`dataset audit` via `dataset-auditor.md`):
   - agent runs verification, deduplication, and export to assemble metrics
   - agent loads test/train splits to verify disjointness and scenario uniqueness
   - agent samples records to detect context-leakage and synthetic fingerprints
   - agent emits a final structured Markdown report with severity-classed findings.

This preserves lineage and keeps the verify-only path resumable.

## Adversarial Security Data

If the dataset intentionally contains prompt injections, jailbreaks, or system-prompt-leak examples, import in injection-tolerant mode.

Red-team, security, pentest, and jailbreak requests now enable this by default from the request text. Use `--allow-injections` to force it explicitly or `--enforce-security-flags` to force strict flagging.

This bypasses prompt-injection regex flagging while still preserving control-character cleanup and normal canonicalization.

## Export Flow

Use this when the verified data already exists in SQLite.

Options:

- preset OpenAI export
- preset HuggingFace export
- flat CSV export
- flat JSONL export
- optional `--plan-file` so exported `instruction` and `context` honor any `model_visibility` rules
- custom flat schema export

## Source-Type Guide

- `generated`: topic-driven examples created by the agent
- `url_reference`: records derived from user-provided URLs or reference documents
- `raw_dataset`: records imported from existing datasets
- `internet_research`: records built from material gathered via browsing/search

## Custom Flat Schema

Start from [`resources/templates/custom_flat_schema.json`](../resources/templates/custom_flat_schema.json).

Rules:

- `mode` must be `flat`
- `columns` must be present
- every column needs a unique `name`
- every column needs a non-empty `source`

Example:

```json
{
  "name": "my-export",
  "mode": "flat",
  "columns": [
    {"name": "prompt", "source": "instruction"},
    {"name": "answer", "source": "response.text"},
    {"name": "difficulty", "source": "metadata.difficulty"}
  ]
}
```

## Research/Evidence Flow

Use this before `Generate Flow` when the dataset should be grounded in real-world material.

1. Run `scripts/research.py` with the user request and coverage plan.
2. Review `research_plan.json`, `sources.jsonl`, `evidence.jsonl`, and `coverage_report.json`.
3. Draft canonical records from evidence chunks; do not copy raw chunks as assistant responses.
4. Put provenance on each real-world record: `metadata.evidence_ids`, `metadata.reference_urls`, `metadata.source_domain`, `metadata.source_quality_score`, and `source_uri`.
5. Import drafted records with `scripts/generate.py --dedup-threshold 0.85`.

`collect.py` remains a low-level fetch/chunk fallback. Its output has `status: collected` and should be treated as raw source material, not a finished dataset.

## Advanced collection flags

`scripts/research.py` accepts these optional flags for tighter control:

- `--max-sources-per-domain N` (default 5) — caps sources per domain to prevent one site dominating evidence.
- `--max-bytes N` (default 2 000 000) — aborts fetches beyond N bytes; returns partial content.
- `--allowed-content-types TYPE ...` — restrict fetching to specific content-type prefixes.
- `--per-domain-rate-limit SECONDS` — per-host rate limit (defaults to `--rate-limit`).

`scripts/dedup.py` flags:

- `--strategy {shingle,tfidf,minhash}` — near-duplicate detection algorithm. `minhash` uses a deterministic MinHash estimator.
- `--code-aware` — normalizes Python code blocks (variable rename, comment strip) before dedup comparison.

## Optional GPT Researcher Backend

The native research module is the default because the skill avoids mandatory external LLM-provider API calls. When a user explicitly wants autonomous deep research and has the required API keys, install optional dependencies and run:

```bash
python3 -m pip install -r requirements-research.txt
python3 scripts/research.py --backend gpt_researcher --query "<topic>"
```

The adapter converts GPT Researcher context/sources into this repo's `sources.jsonl` and `evidence.jsonl` artifacts so downstream generation, verification, coverage, audit, and export stay unchanged.

# Production Quality Hardening

This reference describes optional gates for serious fine-tuning runs.

## Code quality

Enable `code_quality.enabled` to add AST-aware Python checks, JSON parsing, and delimiter/quote balance checks for JavaScript, shell, and SQL snippets.

## Code-aware deduplication

Use:

```bash
python3 scripts/dedup.py --from-status verified_pass --strategy code --threshold 0.92
```

For import-time duplicate rejection, use:

```bash
python3 scripts/generate.py --input drafts.jsonl --dedup-threshold 0.92 --dedup-strategy code
```

## DPO pair quality

Enable `dpo_audit.enabled` to reject empty/identical chosen-rejected pairs, refusal-like rejected responses, missing `metadata.dpo_delta`, implausibly short rejected responses, and excessive chosen/rejected length skew.

## Benchmark contamination

Enable `benchmark_contamination.enabled` to block common public-benchmark fingerprints. This is not a complete detector; it is a deterministic guardrail that forces re-drafting of suspicious records.

## Semantic review batching

Use `scripts/review_batch.py` to build a host-agent review prompt and validate review JSONL without requiring local scripts to call external LLM APIs.

