# Dataset Skill (Antigravity / Claude / Codex)

An agentic dataset-generation skill for agent IDEs, built around tool-native reasoning plus a deterministic local pipeline for normalization, verification, deduplication, export, and data-card generation.

**In Simple Terms:** This tool turns your AI coding assistant into an automated data engineer. You just describe the dataset you need in normal language, and the agent automatically researches, writes examples, filters out bad/duplicate responses, and exports a high-quality dataset ready for model training (SFT or DPO).

## IDE Compatibility

- Antigravity IDE: `.agent/skills/dataset-generator`
- Claude Code: `~/.claude/skills/dataset-generator`
- Codex: `~/.codex/skills/dataset-generator`

## Current Inventory

- Specialized sub-skills: `12`
- Pipeline entry scripts: `6`
- Shared utility modules: `6`
- Internal canonical schema: `1`
- Preset export schemas: `3`
- Automated tests: `24`


## Features

| Capability | Description |
|-----------|-------------|
| `dataset collect` | Fetch content from web searches (5-backend fallback chain), explicit URLs, or local files/repos and emit canonical JSONL for agent-driven dataset creation |
| `dataset generate` | Topic-driven generation, URL/reference structuring, web-research capture, or raw dataset normalization into canonical records |
| `dataset verify` | Heuristic checks, refusal detection, review-file adjudication, and audit-friendly DB-backed verification |
| `dataset audit` | Deep post-generation corpus-quality assessment (split disjointness, context leakage, taxonomy coverage, reasoning variety, synthetic fingerprint detection) |
| `dataset export` | OpenAI, HuggingFace, CSV, and flat JSONL export with automatic data-card generation |
| `dataset-strategy` | Request classification, taxonomy planning, `task_type` selection, and schema planning |
| `seed-generator` | Canonical draft creation for generated, URL-derived, research-derived, or imported datasets |
| `diversity-engine` | Coverage expansion via rewritten augmentations or deterministic metadata variants |
| `quality-filter` | Fast heuristic filtering for placeholders, refusals, weak records, and syntax checks |
| `llm-judge` | Structured review-file contract for semantic pass/fail judgments, behavioral delta, and self-bias mitigation |
| `dpo-pair-generator` | Generates contrastive preference pairs with hard negatives for Direct Preference Optimization (DPO) |
| `deduplicator` | Exact and semantic near-duplicate suppression before export |
| `formatter-exporter` | Preset and custom flat-schema mapping for final user-facing outputs |
| `dataset-auditor` | Evaluates full corpora for synthetic contamination, context leakage, balanced coverage, and holdout contamination |
| `local-collector` | Sub-skill that routes collection through IDE-native tools first, then falls back to `scripts/collect.py` |


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

## Adversarial Security Datasets

The runtime sanitizer always strips control characters, but prompt-injection flagging can be relaxed when you are intentionally building red-team or jailbreak training corpora.

For red teaming, security, pentest, and jailbreak datasets, the scripts now enable this mode by default when the request text signals that intent.

Use the import flags below when you want to force the behavior explicitly:

```bash
python3 scripts/generate.py --input drafts.jsonl --source-type raw_dataset --allow-injections
python3 scripts/augment.py --input augmented.jsonl --source-type raw_dataset --allow-injections
python3 scripts/verify.py --input dataset.jsonl --source-type raw_dataset --allow-injections
```

Use `--enforce-security-flags` to opt back into strict flagging for those requests.

That bypasses prompt-injection regex flagging while preserving other normalization behavior.

## Real-World Grounding & Anti-Synthetic Quality

Standard LLM dataset generation often produces "synthetic-feeling" datasets (e.g., highly templated reasoning, perfectly polished but unnatural prompts, and context leakage). 

The pipeline is intentionally structured to avoid this via **Anti-Synthetic Guardrails**:

- **Research-First Sourcing**: The agent is mandated to prefer real-world source material (forum posts, issue trackers) over pure imagination, aiming for a >60% real-world grounding ratio.
- **Human Imperfection Injection**: Seed records are deliberately varied with typos, ambiguous phrasing, and casual formatting to prevent the model from overfitting to formal prompt templates.
- **Response Architecture Variety**: Responses are explicitly forced into diverse structures (e.g., Socratic pushback, code-first, disagreement) rather than repeating a fixed chain-of-thought skeleton.
- **Corpus-Level Synthetic Audits**: Running `dataset audit` evaluates the corpus for telltale synthetic fingerprints (like uniform sentence lengths or repetitive openings) and structural mode collapse.

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

**Basic SFT Generation**
```text
Generate a 1500-example legal intake dataset with hard edge cases and export it as CSV.
```

**Advanced DPO Generation with Reasoning**
```text
Generate a 1000-example DPO dataset for Python code review focusing on identifying subtle concurrency bugs. I will use this to train an LLM to act as an automated PR reviewer.

Each example should be structured as follows:
- Context: A snippet of Python code using `asyncio` or `threading` with a hidden race condition or deadlock.
- Instruction: "Please review this code for concurrency issues."
- Chosen Response: A <think> block with step-by-step reasoning that correctly identifies the root cause, followed by a polite explanation and fixed code.
- Rejected Response: A plausible-sounding review that misses the bug entirely or suggests a flawed "fix".

Ensure the dataset covers diverse real-world scenarios like asynchronous task cancellation, shared state mutations, and improper lock ordering. Export the dataset in HuggingFace format.
```

**Dataset Normalization / Import**
```text
Normalize this CSV into HuggingFace chat format and deduplicate it.
```

**Audit and Export**
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

`scripts/generate.py` is intentionally an importer/seeder plus SQLite state manager. It does not call external LLM-provider APIs.

## Architecture

![Dataset skill architecture](./docs/media/dataset-skill-architecture.svg)

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


## Roadmap

- Add a standalone `dataset card` command if users want card generation decoupled from export.
- Move toward stronger artifact versioning and per-run workspace layout once larger datasets become a primary use case.
