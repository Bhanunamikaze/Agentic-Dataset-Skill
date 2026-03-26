# formatter-exporter

Use this when the user asks for a final dataset file.

## Principle

- Internal canonical schema is fixed.
- Final export schema is flexible.
- Enforce **Cluster-Based Splitting** (Group Shuffle Split). Ensure records sharing the same vulnerability/scenario fingerprint stay together in either train or test, but never both. This prevents holdout leakage.
- Always output a `canonical.jsonl` artifact alongside any formatted exports. When the coverage plan defines `model_visibility`, exported `instruction` and `context` are sanitized for model consumption while metadata stays intact.

## Presets

- `openai`
- `huggingface`
- `csv`
- `jsonl`

## Custom flat schema

If the user wants custom headers, copy `resources/templates/custom_flat_schema.json` and edit the `columns` list.

Each column uses:

- `name`: the exported header
- `source`: a dotted path from canonical data, for example `instruction` or `metadata.difficulty`

Validation rules:

- schema `mode` must be `flat`
- `columns` must be a non-empty list
- every `name` must be unique and non-empty
- every `source` must be a non-empty dotted path

## Commands

Preset export:

```bash
python3 scripts/export.py --format openai --split 0.1 [--plan-file <coverage_plan.json>]
```

Custom flat CSV:

```bash
python3 scripts/export.py --format csv --schema-file <custom_schema.json> --split 0.1 [--plan-file <coverage_plan.json>]
```

Custom flat JSONL:

```bash
python3 scripts/export.py --format jsonl --schema-file <custom_schema.json> --split 0.1 [--plan-file <coverage_plan.json>]
```

Reference notes: `resources/references/export-schema-pattern.md`
