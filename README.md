# Agentic Dataset Skill

Agentic dataset-generation skill for Codex, Antigravity, and Claude Code.

This repository implements the architecture described in the planning diagrams under [`Plan/`](./Plan):

- tool-native reasoning in `SKILL.md` and `sub-skills/`
- deterministic local pipeline scripts in [`scripts/`](./scripts)
- fixed internal canonical schema in [`resources/internal-schema/`](./resources/internal-schema)
- flexible export schemas in [`resources/target-schemas/`](./resources/target-schemas)
- resumable run state in SQLite under [`workspace/`](./workspace)

## Status

Current implementation supports:

- SFT and DPO canonical records
- topic-driven dataset generation via draft import or seed placeholders
- URL/reference-material and existing-dataset normalization through canonical draft import
- heuristic verification plus review-file adjudication
- exact and near-duplicate suppression
- OpenAI, HuggingFace, CSV, and flat JSONL exports
- automatic data-card generation
- automated tests and CI

## Repo Layout

```text
.
├── SKILL.md
├── install.sh
├── scripts/
├── sub-skills/
├── resources/
├── tests/
├── workspace/
└── Plan/
```

## Install

Codex:

```bash
bash install.sh --target codex --repo-path "$(pwd)" --force
```

Antigravity:

```bash
bash install.sh --target antigravity --project-dir /path/to/project --repo-path "$(pwd)" --force
```

Claude Code:

```bash
bash install.sh --target claude --repo-path "$(pwd)" --force
```

## Core Workflow

1. Use `dataset-strategy` to decide request type, `task_type`, `source_type`, and output schema.
2. Collect or normalize draft records into canonical JSONL.
3. Import drafts with `scripts/generate.py`.
4. Expand coverage with `scripts/augment.py` if needed.
5. Run `scripts/verify.py`.
6. Run `scripts/dedup.py`.
7. Export with `scripts/export.py`.

More detail:

- [Architecture Notes](./docs/architecture.md)
- [Workflow Notes](./docs/workflows.md)

## Quick Commands

Generate/import drafts:

```bash
python3 scripts/generate.py --input drafts.jsonl --source-type generated --tool-context codex
```

Verify imported records:

```bash
python3 scripts/verify.py --from-status raw_generated --review-file review.jsonl
```

Deduplicate:

```bash
python3 scripts/dedup.py --from-status verified_pass
```

Export with a custom flat schema:

```bash
python3 scripts/export.py --format csv --schema-file resources/templates/custom_flat_schema.json --split 0.1
```

## Architecture Fit

This repo follows the planning architecture with one deliberate adaptation:

- The diagrams describe LLM-driven phases.
- In this implementation, those reasoning phases are executed by the host IDE agent using `SKILL.md` and `sub-skills/`.
- The Python layer remains deterministic and does not call external LLM-provider APIs.

## Current Architectural Gaps

- Web collection is orchestrated through the host IDE tools and imported through canonical JSONL drafts, not through a dedicated crawler/collector script.
- The `data-card` stage is automatic during export rather than a standalone script.
- There is no separate `dataset card` command; the data card is produced as an export artifact.

## Validation

Run locally:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
```
