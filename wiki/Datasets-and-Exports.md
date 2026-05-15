# Datasets and Exports

Every pipeline run produces a predictable set of artifacts under `workspace/`. This page maps each artifact to the script that writes it, then walks through the canonical record schema, every export preset, custom flat schemas, DPO preference pairs, the data card, and the corpus-level audit report.

## Workspace Artifacts

| Path | What it is | Written by |
|---|---|---|
| `workspace/run_state.sqlite` | Resumable SQLite state for canonical records, lifecycle status, coverage counters, and review adjudications. | `scripts/utils/db.py` (via every pipeline script) |
| `workspace/build_loop_build_<hash>.sqlite` | Per-build database created by `build_loop.py` so parallel runs do not collide. | `scripts/build_loop.py` |
| `workspace/canonical_train.jsonl` | Validated, deduped training split in canonical schema. | `scripts/export.py` |
| `workspace/canonical_test.jsonl` | Held-out test split with disjoint `scenario_fingerprint`s. | `scripts/export.py` |
| `workspace/DATA_CARD.md` | Provenance, coverage, behaviour profile, and training hints for the corpus. | `scripts/export.py` (delegates to `sub-skills/data-card.md`) |
| `workspace/AUDIT_REPORT.md` | Severity-classed corpus findings with evidence. | `scripts/audit.py` |
| `workspace/audit_report.json` | Machine-readable form of the audit. | `scripts/audit.py --json` |
| `workspace/QUALITY_REPORT.json` | Corpus-level quality metrics (response length, structure, prefix repetition, provenance). | `scripts/quality_report.py` |
| `workspace/coverage_plan.json` | Active coverage plan (target effective count, bucket minimums, joint rules, gates). | Authored by the agent; consumed by every script. |
| `workspace/review_prompt.txt` | Host-agent review prompt for semantic adjudication. | `scripts/review_batch.py` |
| `workspace/research/` | Research pipeline outputs (`research_plan.json`, `sources.jsonl`, `evidence.jsonl`, `coverage_report.json`). | `scripts/research.py` |
| `workspace/collected_<timestamp>.jsonl` | Raw collected source chunks (status `collected`). Not training examples. | `scripts/collect.py` |

See [[Generation Workflow]] for how these artifacts are produced over the lifecycle of a run.

## Canonical Record Schema

The canonical schema is the single in-pipeline record shape for both SFT and DPO. The authoritative definition lives in `resources/internal-schema/canonical_schema.json`. Every record carries `id`, `task_type`, `instruction`, `context`, `response`, `metadata`, and `pipeline_status`.

```json
{
  "id": "rec_018f5a0c",
  "task_type": "sft",
  "instruction": "Summarize the cause of the 2010 flash crash in two sentences.",
  "context": "",
  "response": {
    "format": "single",
    "text": "On 6 May 2010 a large sell algorithm triggered a liquidity vacuum on E-mini S&P 500 futures, and high-frequency feedback drove the Dow Jones down nearly 1000 points in minutes. Markets recovered within 30 minutes once liquidity returned."
  },
  "metadata": {
    "difficulty": "medium",
    "persona": "analyst",
    "subtopic": "market-microstructure",
    "response_shape": "narrative",
    "label": "explanation",
    "evidence_ids": ["ev_2010_sec_report_p4"],
    "source_origin": "real_world",
    "scenario_fingerprint": "sf_9c2d1f"
  },
  "source_uri": "https://www.sec.gov/news/studies/2010/marketevents-report.pdf",
  "pipeline_status": "verified_pass"
}
```

DPO records use `response.format: "preference_pair"` with `chosen` and `rejected` fields — see [DPO Preference Pairs](#dpo-preference-pairs).

## Export Presets

`scripts/export.py` ships four presets. Each preset reads from `pipeline_status: verified_pass` records by default and emits a train/test split sized by `--split`.

### `openai`

```bash
python3 scripts/export.py --format openai --split 0.1
```

Each record becomes a chat-format example with a `messages` array:

```json
{
  "messages": [
    {"role": "system", "content": "You are a senior analyst."},
    {"role": "user", "content": "Summarize the cause of the 2010 flash crash in two sentences."},
    {"role": "assistant", "content": "On 6 May 2010 a large sell algorithm triggered a liquidity vacuum on E-mini S&P 500 futures, and high-frequency feedback drove the Dow Jones down nearly 1000 points in minutes. Markets recovered within 30 minutes once liquidity returned."}
  ]
}
```

Use when you are fine-tuning via the OpenAI API or any chat-format trainer that consumes JSONL with `messages`.

### `huggingface`

```bash
python3 scripts/export.py --format huggingface --split 0.1
```

Writes a `DatasetDict`-style layout with `train`/`test` splits and a `dataset_info.json` companion:

```json
{
  "id": "rec_018f5a0c",
  "instruction": "Summarize the cause of the 2010 flash crash in two sentences.",
  "input": "",
  "output": "On 6 May 2010 a large sell algorithm triggered...",
  "metadata": {
    "difficulty": "medium",
    "persona": "analyst",
    "subtopic": "market-microstructure"
  }
}
```

Use when you plan to load the dataset with `datasets.load_dataset("json", data_files=...)` or push it to a HuggingFace Hub repo.

### `csv`

```bash
python3 scripts/export.py --format csv --split 0.1
```

Default columns: `id`, `task_type`, `instruction`, `context`, `response`, `difficulty`, `persona`, `subtopic`, `source_origin`. One row per record.

Use when downstream tooling expects spreadsheets, when reviewers need a tabular view, or for quick eyeballing inside `pandas`.

### `jsonl`

```bash
python3 scripts/export.py --format jsonl --split 0.1
```

Flat one-record-per-line JSON with the canonical fields collapsed:

```json
{
  "id": "rec_018f5a0c",
  "task_type": "sft",
  "instruction": "Summarize the cause of the 2010 flash crash in two sentences.",
  "context": "",
  "response": "On 6 May 2010 a large sell algorithm triggered a liquidity vacuum...",
  "difficulty": "medium",
  "persona": "analyst",
  "subtopic": "market-microstructure",
  "source_origin": "real_world"
}
```

Use when you want a portable single-file dataset and your trainer reads vanilla flat JSONL.

`--format all` writes every preset side-by-side under `workspace/`.

## Custom Flat Schemas

When the default columns do not match the target trainer, start from `resources/templates/custom_flat_schema.json` instead of inventing an ad hoc shape. The skill enforces the rules below before export.

Schema rules:

- `mode` must be `flat`.
- `columns` must be present and non-empty.
- every column needs a unique `name`.
- every column needs a non-empty `source` (canonical dot path such as `metadata.difficulty` or `response.text`).

Example schema for a prompt/answer trainer that also wants `persona` and `difficulty`:

```json
{
  "name": "compact-sft-export",
  "mode": "flat",
  "columns": [
    {"name": "prompt", "source": "instruction"},
    {"name": "answer", "source": "response.text"},
    {"name": "persona", "source": "metadata.persona"},
    {"name": "difficulty", "source": "metadata.difficulty"}
  ]
}
```

Validate and export:

```bash
python3 scripts/export.py \
    --format csv \
    --schema-file workspace/compact_sft_schema.json \
    --split 0.1
```

The schema file is validated against the canonical record paths before any rows are written. If a column references a missing field, the export aborts.

## DPO Preference Pairs

When the dataset is DPO (preference) data, records carry `response.format: "preference_pair"` with `chosen` and `rejected` strings:

```json
{
  "id": "pref_0a31",
  "task_type": "dpo",
  "instruction": "Refactor this function to remove the nested loop.",
  "context": "def f(xs):\n    out = []\n    for x in xs:\n        for y in xs:\n            if x == y:\n                out.append(x)\n    return out",
  "response": {
    "format": "preference_pair",
    "chosen": "def f(xs):\n    return list(set(xs))",
    "rejected": "def f(xs):\n    return xs"
  },
  "metadata": {
    "difficulty": "easy",
    "persona": "code-reviewer",
    "dpo_delta": "deduplication-fix"
  }
}
```

### OpenAI DPO shape

```json
{
  "input": {
    "messages": [
      {"role": "user", "content": "Refactor this function to remove the nested loop."}
    ]
  },
  "preferred_output": [{"role": "assistant", "content": "def f(xs):\n    return list(set(xs))"}],
  "non_preferred_output": [{"role": "assistant", "content": "def f(xs):\n    return xs"}]
}
```

### HuggingFace DPO shape

```json
{
  "prompt": "Refactor this function to remove the nested loop.",
  "chosen": "def f(xs):\n    return list(set(xs))",
  "rejected": "def f(xs):\n    return xs"
}
```

The Phase 14 gates ensure the chosen side cannot itself be a refusal, contain anti-trope openers, or fall below the grounding floor — see [[Generation Workflow]] for the full list.

## Data Card

`workspace/DATA_CARD.md` is produced by `scripts/export.py` using the `sub-skills/data-card.md` rubric. Sections:

- **Provenance and Statistics** — record counts, train/test sizes, source-type breakdown, source-domain distribution, license notes.
- **Pipeline Coverage Metrics** — bucket coverage against the active coverage plan, joint-bucket completion, response-shape distribution, prefix-repetition stats.
- **Model Behaviour Profiling** — refusal rate, anti-trope rate, persona/difficulty distribution, DPO delta categories.
- **Training Configuration Hints** — suggested batch size, suggested context window, recommended `--split`, and any model-visibility caveats.

Use the data card as the authoritative description of the corpus when handing it off to a fine-tuning team.

## Audit Report

`scripts/audit.py` runs a corpus-level pass over the train/test splits and emits `workspace/AUDIT_REPORT.md` plus `workspace/audit_report.json`. Findings are severity-classed and grouped by:

- **Split disjointness** — `metadata.scenario_fingerprint` must not appear in both train and test.
- **Taxonomy coverage** — every `group_minimums` bucket must have records in both splits.
- **Source diversity** — `metadata.source_domain` and `metadata.source_origin` should not be dominated by one source.
- **Label balance** — `metadata.label` distribution checked against `class_balance` if present.
- **Synthetic fingerprint** — flags suspicious repetition in opening clauses, named entities, or boilerplate.
- **Cluster-fallback rate** — flags excessive use of instruction-word cluster keys when richer fingerprints are missing.
- **Context leakage (Phase 14)** — `audit.py` walks model-visible `instruction` and `context` and flags any plan/system text that leaked into them during generation.

Run on demand against any pair of split files:

```bash
python3 scripts/audit.py \
    --train workspace/canonical_train.jsonl \
    --test workspace/canonical_test.jsonl \
    --plan-file workspace/coverage_plan.json
```

For the failure modes those audit findings raise, see [[Troubleshooting]].
