# Workflow Notes

## Generate Flow

Use this when the user wants a new dataset or wants raw material turned into one.

1. decide request type, `task_type`, `source_type`, and target schema
2. inspect recent runs in SQLite
3. collect or write canonical draft records
4. import drafts with `scripts/generate.py`
5. augment if needed
6. verify
7. deduplicate
8. export

## Verify Flow

Use this when the user already has a file and wants an audit.

1. import the file with `scripts/generate.py --source-type raw_dataset`
2. capture the generated `run_id`
3. run `scripts/verify.py --source-run-id <run_id>`
4. run `scripts/dedup.py --source-run-id <run_id>`
5. export audit-ready outputs

This preserves lineage and keeps the verify-only path resumable.

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
