# Dataset Skill (Antigravity / Claude / Codex)

An agentic dataset-generation skill for agent IDEs, built around tool-native reasoning plus a deterministic local pipeline for normalization, verification, deduplication, export, and data-card generation.

## IDE Compatibility

- Antigravity IDE: `.agent/skills/dataset-generator`
- Claude Code: `~/.claude/skills/dataset-generator`
- Codex: `~/.codex/skills/dataset-generator`

## Current Inventory

- Specialized sub-skills: `9`
- Pipeline entry scripts: `5`
- Shared utility modules: `4`
- Internal canonical schema: `1`
- Preset export schemas: `3`
- Automated tests: `5`

## Features

| Capability | Description |
|-----------|-------------|
| `dataset generate` | Topic-driven generation, URL/reference structuring, web-research capture, or raw dataset normalization into canonical records |
| `dataset verify` | Heuristic checks, refusal detection, review-file adjudication, and audit-friendly DB-backed verification |
| `dataset export` | OpenAI, HuggingFace, CSV, and flat JSONL export with automatic data-card generation |
| `dataset-strategy` | Request classification, taxonomy planning, `task_type` selection, and schema planning |
| `seed-generator` | Canonical draft creation for generated, URL-derived, research-derived, or imported datasets |
| `diversity-engine` | Coverage expansion via rewritten augmentations or deterministic metadata variants |
| `quality-filter` | Fast heuristic filtering for placeholders, refusals, and weak records |
| `llm-judge` | Structured review-file contract for semantic pass/fail judgments inside the IDE |
| `deduplicator` | Exact and near-duplicate suppression before export |
| `formatter-exporter` | Preset and custom flat-schema mapping for final user-facing outputs |

## Automated Pipeline

This repo is an automated pipeline for the deterministic stages:

1. import or seed canonical records
2. augment records
3. verify records
4. deduplicate verified records
5. export artifacts and generate a data card

What is not fully autonomous by design:

- browsing/search-driven evidence collection
- taxonomy design
- semantic judging
- custom export-schema selection

Those reasoning-heavy phases are handled by the host IDE agent via [`SKILL.md`](./SKILL.md) and [`sub-skills/`](./sub-skills/), which matches the Codex / Antigravity / Claude Code skill model.

## Architecture

Primary skill architecture:

![Dataset skill architecture](./docs/media/dataset-skill-architecture.svg)

Industry-style pipeline phases:

![Industry pipeline](./docs/media/industry-pipeline.svg)

## LLM-First Workflow

This skill follows a reasoning-first pattern:

1. classify the user request
2. choose `task_type`, `source_type`, and output schema
3. collect evidence or draft canonical records
4. run deterministic scripts for stateful processing
5. export only validated, deduplicated artifacts

The fixed/flexible split is intentional:

- internal canonical schema: fixed
- final user-facing export schema: flexible

## Installation (All IDEs)

### Quick Install Script

```bash
# 1) Clone
git clone https://github.com/Bhanunamikaze/Agentic-Dataset-Skill.git
cd Agentic-Dataset-Skill

# 2) Install for your target
# Antigravity (project-local):
bash install.sh --target antigravity --project-dir /path/to/your/project

# Claude:
bash install.sh --target claude

# Codex:
bash install.sh --target codex

# Global user install (Claude + Codex):
bash install.sh --target global

# All targets:
bash install.sh --target all --project-dir /path/to/your/project

# Install from another local checkout:
bash install.sh --target codex --repo-path /path/to/Agentic-Dataset-Skill
```

### Install Directly From GitHub

```bash
curl -fsSL https://raw.githubusercontent.com/Bhanunamikaze/Agentic-Dataset-Skill/main/install.sh | \
  bash -s -- --target codex
```

## Prompt Routing Examples

| You type... | Route | Main phases used |
|-------------|-------|------------------|
| `Generate a 500-row medical triage dataset` | topic-driven generation | strategy -> seed -> verify -> dedup -> export |
| `Turn these URLs into a training dataset` | URL/reference structuring | strategy -> seed -> verify -> dedup -> export |
| `Normalize this CSV into OpenAI JSONL` | existing-dataset normalization | strategy -> seed -> verify -> export |
| `Verify and score this dataset.jsonl` | verify-only audit | data-verifier -> verify -> dedup -> export |
| `Export the verified set with custom headers` | export-only | formatter-exporter -> export |

## Repository Docs

- [Architecture Notes](./docs/architecture.md)
- [Workflow Notes](./docs/workflows.md)
- [Primary Skill Contract](./SKILL.md)

## Current Architectural Gaps

- Web collection is still orchestrated through the host IDE tools and imported through canonical drafts, not through a dedicated crawler/collector script.
- The `data-card` phase is implemented automatically during export rather than through a separate top-level command.
- There is no separate `dataset card` command; the data card is produced as an export artifact.

## Validation

Run locally:

```bash
python3 -m unittest discover -s tests -p 'test*.py'
```
