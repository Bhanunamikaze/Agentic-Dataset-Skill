# seed-generator

Use this after `dataset-strategy`.

## Goal

Create or normalize draft records into the fixed canonical schema.

## Operating modes

### Topic-driven generation

- Draft canonical records directly in JSONL.
- Spread examples across taxonomy, persona, and difficulty.
- Keep records concrete and non-redundant.

### URL or reference-material structuring

- Use available browsing, file-reading, and search tools in the IDE.
- Extract facts, examples, or source passages.
- Convert them into canonical records instead of copying raw source dumps.

### Existing dataset normalization

- Map source columns into canonical fields.
- Preserve provenance in metadata.
- Keep the source URI/path when available.

## Output path

Write draft records to a JSONL file, then load them with:

```bash
python3 scripts/generate.py --input <drafts.jsonl> --source-type <generated|url_reference|raw_dataset|internet_research> --tool-context <codex|claude|antigravity>
```

The imported drafts will enter the pipeline as `raw_generated` records unless they still contain explicit placeholder responses, in which case they remain `seeded`.

## Required metadata

Each canonical record should carry enough metadata for later export and audit:

- `difficulty`
- `persona`
- `source_type`
- optional provenance such as `reference_urls`, tags, source path, or notes

## Seed-only fallback

If you only need placeholder slots before writing full examples:

```bash
python3 scripts/generate.py --topic "<topic>" --count <n> --task-type <sft|dpo>
```
