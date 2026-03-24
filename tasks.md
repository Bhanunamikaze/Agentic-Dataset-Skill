# Dataset-Generator-Skill Task Tracker

## Build Contract

- Status: `in_progress`
- Goal: Build an agentic dataset generation skill for Codex, Antigravity, and Claude Code that supports SFT and DPO workflows, tool-guided data collection, resumable SQLite state, verification, deduplication, export, and data-card generation.
- Source documents:
  - `Plan/plan.md`
  - `docs/media/dataset-skill-architecture.svg`
  - `docs/media/industry-pipeline.svg`

## Confirmed Decisions

- Status: `completed`
- Support both SFT and DPO automatically based on the user's request.
- Prefer `target-schemas/` naming for export schemas and keep the structure internally consistent.
- Generate the data card automatically as an artifact of export instead of as a separate top-level command.
- Support both JSONL and CSV inputs/outputs in v1.
- This is a tool-native skill for Codex, Antigravity, and Claude Code, not a direct LLM-provider API pipeline.
- The agent should use built-in IDE capabilities and user-provided material for search, browsing, reading, and reasoning, while local scripts handle deterministic transforms.
- Support three primary user entry paths:
  - User asks the LLM to generate a dataset from a topic or task description.
  - User provides URLs or reference data to be structured into a dataset.
  - User provides existing datasets from various sources to be normalized, verified, deduplicated, and exported.
  - User asks the agent to search the internet and compile a dataset from discovered material using the IDE's own browsing/search tools.

## Task List

| ID | Task | Details | Status |
| --- | --- | --- | --- |
| T01 | Repository bootstrap | Initialize git, create the required folder structure, and add baseline ignore rules where needed. | `completed` |
| T02 | Tracker maintenance | Keep this file current with scope, progress, and change summaries across the build. | `in_progress` |
| T03 | Multi-target installer | Create `install.sh` for Antigravity, Claude, and Codex installation targets, with optional helper-script dependency installation. | `completed` |
| T04 | Canonical schema | Define `resources/internal-schema/canonical_schema.json` for a unified record model that can represent both SFT and DPO examples. | `completed` |
| T05 | Workspace bootstrap | Create `workspace/` artifacts and a SQLite initialization layer in `scripts/utils/db.py` for resumable runs and record lifecycle tracking. | `completed` |
| T06 | Shared runtime utilities | Add reusable utilities for prompt loading, schema helpers, CSV/JSONL parsing, structured record conversion, and local run-state management. | `completed` |
| T07 | Generation pipeline | Implement `scripts/generate.py` for turning agent-collected or user-provided material into canonical dataset records and tracked run state. | `completed` |
| T08 | Augmentation pipeline | Implement `scripts/augment.py` for diversity transformations such as tone shifts, persona changes, difficulty changes, and adversarial variations. | `completed` |
| T09 | Verification pipeline | Implement `scripts/verify.py` with heuristic refusal detection, schema validation, and structured review support for LLM-as-judge steps done inside the IDE. | `completed` |
| T10 | Deduplication pipeline | Implement `scripts/dedup.py` with exact and near-duplicate detection using MinHash/LSH. | `completed` |
| T11 | Export pipeline | Implement `scripts/export.py` for OpenAI/Hugging Face style JSONL and CSV exports, dataset splits, and automatic data-card output. | `completed` |
| T12 | Input ingestion | Support URL/reference-data workflows, existing dataset ingestion workflows, and tool-collected web research workflows that normalize material into the canonical schema. | `completed` |
| T13 | Sub-skill prompts | Create the markdown prompt files in `sub-skills/` for strategy, seeding, diversity, filtering, judging, deduplication guidance, export formatting, data card generation, and verification-only flows. | `completed` |
| T14 | Skill orchestrator | Create `SKILL.md` as the orchestration entry point for `dataset generate`, `dataset verify`, and `dataset export`, including resume detection and route selection by user intent across the three IDEs. | `completed` |
| T15 | Verification and QA | Run local smoke checks, validate the schema and scripts, and document any limits tied to local tool availability rather than provider integrations. | `completed` |
| T16 | Automated tests | Add unit and integration-style tests for canonical normalization, DB-backed pipeline flows, and export schema behavior. | `completed` |
| T17 | CI workflow | Add a GitHub Actions workflow that installs dependencies and runs compile/test checks on pushes and pull requests. | `completed` |
| T18 | Export schema validation | Validate custom flat export schemas strictly before export runs and fail with actionable errors. | `completed` |
| T19 | Richer export reporting | Expand export summaries and generated data cards with column lists, distributions, artifact lists, and run metadata. | `completed` |
| T20 | Skill behavior tightening | Tighten the orchestration contract in `SKILL.md` and sub-skills so each route maps clearly to the deterministic script layer. | `completed` |
| T21 | GitHub documentation | Add GitHub-facing repository documentation for installation, architecture, workflows, and current gaps. | `completed` |

## Open Technical Notes

- Status: `in_progress`
- The canonical schema needs to support both single-response and preference-pair records without forcing separate pipelines.
- Tool-native reasoning will live in `SKILL.md` and sub-skills, while Python scripts stay deterministic and operate on already-collected material or local files.
- URL ingestion and internet-assisted collection will be designed into the architecture, but any live network-dependent paths may need to remain unexecuted in this sandboxed environment.

## Change Log

- Status: `in_progress`
- 2026-03-24: Read the planning documents, resolved the main contract questions with the user, and created the initial tracked task ledger.
- 2026-03-24: Re-scoped the build away from direct LLM-provider APIs after reviewing the user's `Agentic-SEO-Skill` repository usage pattern on GitHub.
- 2026-03-24: Added the multi-target installer, canonical schema, workspace scaffold, and SQLite bootstrap layer; validated installer help, schema parsing, and DB initialization.
- 2026-03-24: Added shared utilities for file IO, schema validation, canonical normalization, and DB run-state migration; validated imports and normalization behavior.
- 2026-03-24: Implemented and smoke-tested `generate.py` and `augment.py`, including seed creation, SQLite imports, and DB-backed metadata variant generation.
- 2026-03-24: Implemented and smoke-tested `verify.py`, `dedup.py`, and `export.py`, including review-file adjudication, duplicate suppression, flexible flat-schema export, and automatic data-card generation.
- 2026-03-24: Added the full sub-skill layer, root `SKILL.md`, custom export-schema template, and final installer exclusions; validated Codex/Antigravity installs and custom-schema export behavior.
- 2026-03-24: Added unit/integration tests and a GitHub Actions CI workflow; validated local compile checks and `unittest` execution.
- 2026-03-24: Tightened flat export schema validation and expanded export summaries/data cards with richer dataset statistics; validated with updated tests.
- 2026-03-24: Fixed imported draft status promotion in `generate.py`, tightened orchestration/sub-skill routing, and added GitHub-facing docs for architecture and workflows.
- 2026-03-24: Moved architecture SVGs into `docs/media/` and reshaped the README around the `Agentic-SEO-Skill` documentation style.
