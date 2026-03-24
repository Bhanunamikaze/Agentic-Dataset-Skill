# Workflow Notes

## Generate Flow

Use this when the user wants a new dataset or wants raw material turned into one.

1. decide request type, `task_type`, `source_type`, and target schema
2. set the target example count
3. if the user does not specify a size, default to `500`
4. generate or collect records in batches until the target count is reached
5. inspect recent runs in SQLite
6. collect or write canonical draft records
7. import drafts with `scripts/generate.py`
8. augment if needed
9. verify
10. deduplicate
11. export

## Verify Flow

Use this when the user already has a file and wants an audit.

1. import the file with `scripts/generate.py --source-type raw_dataset`
2. capture the generated `run_id`
3. run `scripts/verify.py --source-run-id <run_id>`
4. run `scripts/dedup.py --source-run-id <run_id>`
5. export audit-ready outputs

This preserves lineage and keeps the verify-only path resumable.

## Adversarial Security Data

If the dataset intentionally contains prompt injections, jailbreaks, or system-prompt-leak examples, import with `--allow-injections`.

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
