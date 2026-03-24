# Dataset Skill (Antigravity / Claude / Codex)

[![CI](https://github.com/Bhanunamikaze/Agentic-Dataset-Skill/actions/workflows/ci.yml/badge.svg)](https://github.com/Bhanunamikaze/Agentic-Dataset-Skill/actions/workflows/ci.yml)

An agentic dataset-generation skill for agent IDEs, built around tool-native reasoning plus a deterministic local pipeline for normalization, verification, deduplication, export, and data-card generation.

## IDE Compatibility

- Antigravity IDE: `.agent/skills/dataset-generator`
- Claude Code: `~/.claude/skills/dataset-generator`
- Codex: `~/.codex/skills/dataset-generator`

## Current Inventory

- Specialized sub-skills: `9`
- Pipeline entry scripts: `5`
- Shared utility modules: `5`
- Internal canonical schema: `1`
- Preset export schemas: `3`
- Automated tests: `8`


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

Recommended path:

- clone the repository
- review `install.sh`
- run it locally

Convenience remote install exists, but pipe-to-shell is intentionally not the recommended default.

### Safer Remote Install With Checksum

For stronger integrity, pin to a release tag or commit SHA instead of `main`.

```bash
curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/Agentic-Dataset-Skill/main/install.sh
curl -fsSLO https://raw.githubusercontent.com/Bhanunamikaze/Agentic-Dataset-Skill/main/install.sh.sha256
sha256sum -c install.sh.sha256
bash install.sh --target codex
```

Python dependency install:

```bash
python3 -m pip install -r requirements.txt
```

## Example Prompts

### How prompts route to the skill

You do not need to use explicit flags or command syntax. Natural-language prompts are enough.

- To get a production-sized dataset, just describe the dataset. If you do not specify a size, the skill should target `500` records.
- To get a larger or smaller dataset, state the number explicitly.
- To verify or export an existing dataset, say that directly and the skill should route into the DB-backed audit/export flow.

| You type... | Scope | Route | Main phases used |
|-------------|-------|-------|------------------|
| `Generate a medical triage dataset` | topic-driven generation | default-size generation | strategy -> seed -> verify -> dedup -> export |
| `Generate a 2000-example customer support dataset in OpenAI JSONL` | topic-driven generation | user-sized generation | strategy -> seed -> verify -> dedup -> export |
| `Turn these URLs into a training dataset` | URL/reference structuring | source-to-dataset conversion | strategy -> seed -> verify -> dedup -> export |
| `Use web research to build a fintech FAQ dataset` | internet-research generation | research-driven generation | strategy -> seed -> verify -> dedup -> export |
| `Normalize this CSV into OpenAI JSONL` | existing-dataset normalization | import and reshape | strategy -> seed -> verify -> export |
| `Verify and score this dataset.jsonl` | verify-only audit | audit flow | data-verifier -> verify -> dedup -> export |
| `Export the verified set with custom headers` | export-only | export shaping | formatter-exporter -> export |

### Prompt examples

```text
Generate a medical triage dataset for SFT.
```

```text
Generate a 1500-example legal intake dataset with hard edge cases and export it as CSV.
```

```text
Turn these URLs into a fine-tuning dataset and keep the source URLs in metadata.
```

```text
Use web research to build a cybersecurity FAQ dataset for customer support.
```

```text
Normalize this CSV into HuggingFace chat format and deduplicate it.
```

```text
Verify this dataset, remove weak examples, and export custom columns: prompt, answer, persona, difficulty.
```


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

## Default Dataset Size

For generation requests, the default target size is `500` records unless the user explicitly asks for a different number or asks for a small prototype/sample.

Practical rule:

- no size specified -> target `500`
- explicit size specified -> honor the requested count
- explicit prototype/sample wording -> smaller output is acceptable

Why `500`:

- it is a practical default that is large enough to produce a usable first-pass dataset while still being realistic for a single agent-driven session

## Repository Docs

- [Architecture Notes](./docs/architecture.md)
- [Workflow Notes](./docs/workflows.md)
- [Primary Skill Contract](./SKILL.md)
- [Contributing Guide](./CONTRIBUTING.md)
- [Security Policy](./SECURITY.md)
- [Task Tracker](./docs/tasks.md)


## Roadmap

- Add a dedicated local collector for URL and web-evidence ingestion instead of relying entirely on host-IDE collection.
- Add a standalone `dataset card` command if users want card generation decoupled from export.
- Move toward stronger artifact versioning and per-run workspace layout once larger datasets become a primary use case.
- Migrate backlog items from `docs/tasks.md` into GitHub Issues and milestones.
