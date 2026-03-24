# Architecture Notes

## Diagram Mapping

The plan diagrams define four main layers:

1. primary orchestrator
2. cognitive sub-skills
3. deterministic scripts
4. resources and workspace state

This repository maps those layers as follows.

## 1. Primary Orchestrator

- [`SKILL.md`](../SKILL.md)

Responsibilities:

- route user intent
- decide whether the run is generate, verify, or export
- decide when to resume or start fresh
- select the relevant sub-skills
- choose the output schema path

## 2. Cognitive Layer

- [`sub-skills/dataset-strategy.md`](../sub-skills/dataset-strategy.md)
- [`sub-skills/seed-generator.md`](../sub-skills/seed-generator.md)
- [`sub-skills/diversity-engine.md`](../sub-skills/diversity-engine.md)
- [`sub-skills/quality-filter.md`](../sub-skills/quality-filter.md)
- [`sub-skills/llm-judge.md`](../sub-skills/llm-judge.md)
- [`sub-skills/deduplicator.md`](../sub-skills/deduplicator.md)
- [`sub-skills/formatter-exporter.md`](../sub-skills/formatter-exporter.md)
- [`sub-skills/data-card.md`](../sub-skills/data-card.md)
- [`sub-skills/data-verifier.md`](../sub-skills/data-verifier.md)

Responsibilities:

- reasoning
- planning
- taxonomy design
- schema choice
- judging guidance
- workflow selection

## 3. Deterministic Script Layer

- [`scripts/generate.py`](../scripts/generate.py)
- [`scripts/augment.py`](../scripts/augment.py)
- [`scripts/verify.py`](../scripts/verify.py)
- [`scripts/dedup.py`](../scripts/dedup.py)
- [`scripts/export.py`](../scripts/export.py)

Responsibilities:

- normalize/import canonical records
- manage resumable SQLite state
- apply deterministic heuristics
- apply duplicate suppression
- export into fixed presets or custom flat schemas

## 4. Resources and Workspace

- canonical schema: [`resources/internal-schema/canonical_schema.json`](../resources/internal-schema/canonical_schema.json)
- preset export schemas: [`resources/target-schemas/`](../resources/target-schemas/)
- custom schema starter: [`resources/templates/custom_flat_schema.json`](../resources/templates/custom_flat_schema.json)
- audit/export references: [`resources/references/`](../resources/references/)
- runtime state: [`workspace/`](../workspace/)

## Key Design Decision

The biggest adaptation from the plan is the execution model:

- Reasoning phases are not implemented as external API calls.
- They are executed by the host coding assistant environment.
- Local scripts handle only deterministic transforms and persistence.

That keeps the pipeline aligned with Codex, Antigravity, and Claude Code skill usage.
