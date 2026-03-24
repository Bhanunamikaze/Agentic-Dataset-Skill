---
name: dataset-generator
description: Use this when the user wants to generate, normalize, verify, deduplicate, or export training datasets for Codex, Antigravity, or Claude Code from topics, URLs, reference material, web research, or existing JSONL/CSV files. Supports SFT and DPO workflows, custom export schemas, and deterministic local pipeline scripts.
---

# Dataset Generator

This skill is a tool-native dataset pipeline for Codex, Antigravity, and Claude Code.

- Use the IDE's own tools for browsing, reading, search, and reasoning.
- Use local Python scripts for deterministic normalization, state tracking, verification, deduplication, and export.
- Do not call external LLM-provider APIs as part of this skill.

## Command surface

- `dataset generate "<request>" --count <n>`
- `dataset verify <path/to/file>`
- `dataset export --format <openai|huggingface|csv|jsonl|all> [--schema-file path] [--split 0.1]`

## Core architecture

- `sub-skills/` contains the cognitive instructions.
- `scripts/` contains deterministic helpers.
- `resources/internal-schema/canonical_schema.json` is the fixed pipeline backbone.
- `resources/target-schemas/` contains preset export profiles.
- `resources/templates/custom_flat_schema.json` is the starting point for custom headers.

## Fixed vs flexible schema

- The canonical internal schema is fixed.
- The final export schema is not universal and must be chosen per user request.
- For custom CSV or flat JSONL headers, create or update a schema file and pass it to `scripts/export.py`.

Read `sub-skills/dataset-strategy.md` first whenever the target output schema is not already obvious.

## Workflow selection

### 1. `dataset generate`

Use this when the user wants a new dataset or wants source material structured into one.

1. Read `sub-skills/dataset-strategy.md` and explicitly decide:
   - request type
   - `task_type`
   - `source_type`
   - target export schema
   - whether this is a fresh run or a resume
2. If existing runs may matter, inspect the SQLite state before generating:

```bash
python3 -c "from scripts.utils.db import initialize_database, get_connection, list_runs; initialize_database(); conn = get_connection(); print([dict(row) for row in list_runs(conn, limit=5)]); conn.close()"
```

If there is a relevant unfinished or recent run, ask whether to resume or start fresh.

3. Choose the source route:

- Topic-driven synthetic generation:
  - Read `sub-skills/seed-generator.md`.
  - Draft canonical JSONL records and import them with `--source-type generated`.
- URL or reference-material structuring:
  - Read `sub-skills/seed-generator.md`.
  - Use the IDE's browsing/search/file tools to collect material, then write canonical JSONL drafts and import them with `--source-type url_reference`.
- Existing dataset restructuring:
  - Read `sub-skills/seed-generator.md`.
  - Normalize the source dataset into canonical JSONL and import it with `--source-type raw_dataset`.
- Internet-research dataset building:
  - Use the IDE's browsing/search tools first, then import canonical JSONL drafts with `--source-type internet_research`.

4. Load draft records into SQLite:

```bash
python3 scripts/generate.py --input <drafts.jsonl> --source-type <generated|url_reference|raw_dataset|internet_research> --tool-context <codex|claude|antigravity>
```

Imported drafts are promoted into the runnable pipeline with status `raw_generated` unless they are explicit placeholder seeds.

5. If augmentation is needed, read `sub-skills/diversity-engine.md` and either import rewritten augmentations or create metadata variants:

```bash
python3 scripts/augment.py --input <augmented.jsonl> --tool-context <codex|claude|antigravity>
```

Or deterministic metadata variants:

```bash
python3 scripts/augment.py --from-status raw_generated --persona expert --difficulty hard
```

6. Run heuristic verification:

```bash
python3 scripts/verify.py --from-status raw_generated --from-status augmented
```

7. If semantic judging is needed, read `sub-skills/llm-judge.md`, produce a review file, then apply it:

```bash
python3 scripts/verify.py --from-status raw_generated --review-file <review.jsonl>
```

8. Deduplicate passing records:

```bash
python3 scripts/dedup.py --from-status verified_pass
```

9. Read `sub-skills/formatter-exporter.md` and export the dataset plus data card:

```bash
python3 scripts/export.py --format <openai|huggingface|csv|jsonl|all> [--schema-file <schema.json>] [--split 0.1]
```

### 2. `dataset verify`

Use this when the user already has a file and wants an audit or cleanup pass.

Read `sub-skills/data-verifier.md`, then run:

```bash
python3 scripts/generate.py --input <dataset.jsonl_or_csv> --source-type raw_dataset --tool-context <codex|claude|antigravity>
python3 scripts/verify.py --from-status raw_generated --source-run-id <run_id_from_generate> [--review-file <review.jsonl>]
python3 scripts/dedup.py --from-status verified_pass --source-run-id <run_id_from_generate>
python3 scripts/export.py --format csv --split 0.0
```

Prefer the DB-backed route above so the audit remains resumable and traceable.

### 3. `dataset export`

Use this when the verified data already exists in SQLite and the user wants a specific output shape.

Read `sub-skills/formatter-exporter.md` if the schema is not obvious.

Preset export:

```bash
python3 scripts/export.py --format openai --split 0.1
```

Custom flat export:

```bash
python3 scripts/export.py --format csv --schema-file <custom_schema.json> --split 0.1
```

The flat schema file must validate before export. If the user wants custom headers, start from `resources/templates/custom_flat_schema.json` instead of inventing an ad hoc file shape.

## Reference files

- `sub-skills/dataset-strategy.md`
- `sub-skills/seed-generator.md`
- `sub-skills/diversity-engine.md`
- `sub-skills/quality-filter.md`
- `sub-skills/llm-judge.md`
- `sub-skills/deduplicator.md`
- `sub-skills/formatter-exporter.md`
- `sub-skills/data-card.md`
- `sub-skills/data-verifier.md`
- `resources/references/llm-audit-rubric.md`
- `resources/references/export-schema-pattern.md`
