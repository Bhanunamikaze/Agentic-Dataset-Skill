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
2. set the target example count
3. if the user does not specify a size, default to `500`
4. generate or collect records in batches until the target count is reached
5. inspect recent runs in SQLite
6. collect or write canonical draft records
7. import drafts with `scripts/generate.py`
8. augment if needed
9. generate preference pairs using `dpo-pair-generator` if `task_type` is `dpo`
10. verify
11. deduplicate
12. export

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
