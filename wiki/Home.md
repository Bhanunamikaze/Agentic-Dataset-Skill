# AI Dataset Generator Wiki

AI Dataset Generator is a tool-native dataset pipeline for Claude Code, Codex, Antigravity, Cursor, Windsurf, Continue, Copilot, and Cline. It splits work between reasoning (the IDE agent) and deterministic processing (local Python + SQLite).

| At a glance | Current state |
|---|---|
| Latest release tag | `v0.1.0` |
| Sub-skills | 13 |
| Pipeline scripts | 14 |
| Utility modules | 15 (in `scripts/utils/`) |
| Test suite | 2769 lines (`tests/test_pipeline.py`) |
| Main deliverables | `DATA_CARD.md`, `AUDIT_REPORT.md`, `canonical_train.jsonl`, exported dataset files |

## Start Here

| Goal | Go to | What you get |
|---|---|---|
| Install the skill | [[Installation]] | Per-target install commands for Claude Code, Codex, Antigravity, Cowork, Cursor, Windsurf, Continue, Copilot, Cline. |
| Learn the commands | [[Command Reference]] | The `dataset generate`, `dataset collect`, `dataset verify`, `dataset audit`, and `dataset export` command map plus coverage-plan keys. |
| Copy a complete prompt | [[Example Prompts]] | Long-form prompts for SFT, DPO, URL conversion, research grounding, normalization, audit, red-team, and custom export. |
| Understand the generation flow | [[Generation Workflow]] | Strategy → seed/collect → batch build loop → verify → review → dedup → export, mapped to the actual scripts. |
| Inspect generated artifacts | [[Datasets and Exports]] | `run_state.sqlite`, `canonical_train.jsonl`, `DATA_CARD.md`, `AUDIT_REPORT.md`, `QUALITY_REPORT.json`, and every export format. |
| Find a script | [[Script Inventory]] | Start-here groupings plus the full 14-script + 15-utility-module inventory. |
| Package or release | [[Release and Packaging]] | Runtime allowlist, tag publishing workflow, and `--online --ref` install resolution. |
| Fix common failures | [[Troubleshooting]] | SQLite locks, dedup thresholds, refusal-regex misfires, missing evidence ids, grounding gaps, Playwright, and split leakage. |

## Fast Path

### 1. Install for Codex

```bash
curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/ai-dataset-generator/main/install.sh
bash install.sh --online --target codex --force
```

### 2. Generate a 1500-example dataset

```text
dataset generate "Generate a 1500-example customer support dataset"
```

Natural-language is enough — the skill routes the request through `dataset-strategy` → `seed-generator` → `build_loop.py` → `verify.py` → `dedup.py` → `export.py`.

### 3. Verify the result

```bash
python3 ~/.codex/skills/dataset-generator/scripts/audit.py \
    --train workspace/canonical_train.jsonl \
    --test workspace/canonical_test.jsonl
```

The auditor runs split disjointness, scenario-fingerprint, taxonomy coverage, and context-leakage checks and emits `workspace/AUDIT_REPORT.md` (or stdout JSON with `--json`).

## Choose the Right Workflow

| If you need... | Use this command | Primary outputs |
|---|---|---|
| A new topic-driven SFT dataset | `dataset generate "<request>" [--count N]` | `canonical_train.jsonl`, `canonical_test.jsonl`, `DATA_CARD.md` |
| A new DPO preference dataset | `dataset generate "DPO dataset for <task>"` | Preference JSONL with `chosen`/`rejected`, `DATA_CARD.md` |
| URL-to-dataset conversion | `dataset collect "<topic>" --urls <url1> <url2>` then `dataset generate` | Collected JSONL → canonical records → exports |
| Web-research grounded dataset | `dataset generate "Use web research to build a <topic> dataset"` | Research artifacts under `workspace/research/` plus grounded canonical records |
| Normalize an existing dataset | `dataset verify <file>` | `verified_pass` records in SQLite plus re-exported file |
| Structured quality assessment | `dataset audit <file>` | `AUDIT_REPORT.md` with severity-classed findings |
| Export-only shape change | `dataset export --format <openai|huggingface|csv|jsonl|all>` | Train/test files in the requested shape |

## What Makes the Pipeline Useful

The pipeline distinguishes raw imports from validated records by tracking explicit statuses inside SQLite:

- `collected`: raw fetched content. Not a training example.
- `raw_generated`: drafts imported through `generate.py`. Awaiting verification.
- `augmented`: post-augmentation drafts. May still need rewriting.
- `rewrite_required`: scaffolding-only metadata variants that cannot pass verify.
- `verified_pass` / `verified_fail`: heuristic and review outcomes.
- `judge_pending`: passed heuristics but missing semantic review.
- `deduped`: removed by near-duplicate detection.

A run is only complete when post-dedup effective count and every coverage-plan bucket minimum are met. Inflated raw counts are not success.

## What Is Inside

| Area | Examples |
|---|---|
| Strategy and planning | `sub-skills/dataset-strategy.md`, `dpo-pair-generator.md`, `research-planner.md` |
| Source collection | `scripts/collect.py`, `scripts/research.py`, `scripts/browser_collect.py`, `scripts/grounding.py` |
| Generation orchestration | `scripts/generate.py`, `scripts/augment.py`, `scripts/build_loop.py`, `scripts/coverage.py` |
| Verification and review | `scripts/verify.py`, `scripts/dedup.py`, `scripts/review_batch.py`, `sub-skills/llm-judge.md` |
| Audit and export | `scripts/audit.py`, `scripts/quality_report.py`, `scripts/export.py` |
| Resources | `resources/internal-schema/canonical_schema.json`, `resources/target-schemas/`, `resources/templates/custom_flat_schema.json` |

## Source of Truth

The installed skill runtime is intentionally small:

- `SKILL.md`
- `scripts/`
- `sub-skills/`
- `resources/`

The repository also contains `tests/`, `docs/`, `workspace/`, governance files, and this wiki source, but those are not required inside release skill bundles.

Use these pages for human documentation. Use `SKILL.md` and the files under `sub-skills/` and `resources/` for runtime behavior.

## Maintenance Signals

The repo validates:

- Python script compilation
- Sub-skill / script inventory drift
- Pipeline regression tests under `tests/test_pipeline.py`
- Coverage-plan schema for required-field, provenance, and joint-bucket rules

Plan files under `resources/templates/` (`production_quality_plan.json`, `custom_flat_schema.json`) are the canonical starting points for new coverage and export configurations.
