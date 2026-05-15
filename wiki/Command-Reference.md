# Command Reference

Use these commands inside an agent that has the skill installed. The skill also routes natural-language requests directly — explicit `dataset <subcommand>` syntax is optional.

## Command Surface

| Command | What it does | Key flags | Primary output |
|---|---|---|---|
| `dataset generate "<request>"` | Strategy + seed + batch build loop to produce a new dataset. Defaults to `500` records when no size is given. | `--count <n>` | `workspace/canonical_train.jsonl`, `workspace/canonical_test.jsonl`, `DATA_CARD.md` |
| `dataset collect "<topic or query>"` | Fetches source material from URLs, web search, or local files for the agent to draft canonical records from. | `--urls <url1> <url2>`, `--paths <dir>`, `--max-results <n>` (default `10`), `--tool-context <codex\|claude\|antigravity>` | `workspace/collected_<timestamp>.jsonl` |
| `dataset verify <path>` | Imports a file, runs heuristic checks, optional review-file adjudication, dedup, and re-exports. | `--review-file <review.jsonl>`, `--plan-file <coverage_plan.json>`, `--allow-injections`, `--enforce-security-flags` | `workspace/canonical_train.jsonl`, `verified_pass` records in SQLite |
| `dataset audit [<path>]` | Three-phase quality assessment: record-level checks, corpus-level disjointness/leakage, structured report. | (delegates to `verify.py`, `dedup.py`, `export.py`) | `workspace/AUDIT_REPORT.md` |
| `dataset export` | Shapes verified records into a fixed preset or custom flat schema. | `--format <openai\|huggingface\|csv\|jsonl\|all>`, `--schema-file <path>`, `--split <0.0-0.5>`, `--plan-file <coverage_plan.json>` | Train/test files in the requested shape, plus optional `DATA_CARD.md` |

## Natural-Language Routing

You do not need explicit flags. The skill's orchestration layer routes natural-language intent to the right sub-skill and script. Some patterns:

| You type... | Scope | Route |
|---|---|---|
| `Generate a medical triage dataset` | topic-driven generation | strategy → seed → build_loop → export |
| `Generate a 2000-example customer support dataset in OpenAI JSONL` | sized SFT generation | strategy → seed → build_loop → export (`--format openai`) |
| `Turn these URLs into a training dataset` | URL/reference structuring | strategy → collect → seed → build_loop → export |
| `Use web research to build a fintech FAQ dataset` | internet-research generation | research-planner → research → seed → build_loop → export |
| `Normalize this CSV into OpenAI JSONL` | existing-dataset normalization | strategy → seed → verify → export |
| `Verify and score this dataset.jsonl` | verify-only audit | data-verifier → verify → dedup → export |
| `Audit this dataset for leakage and synthetic patterns` | corpus audit | dataset-auditor → audit |
| `Export the verified set with custom headers` | export shaping | formatter-exporter → export |
| `Generate a DPO dataset for Python code review` | DPO generation | strategy → dpo-pair-generator → verify → export |
| `Generate red-team prompt-injection training data` | adversarial corpus | strategy → seed → generate (`--allow-injections`) → verify |

Default size rule: if the user does not specify a target count, `dataset generate` targets `500` records. If they explicitly ask for a sample or prototype, smaller results are acceptable.

## Coverage Plan Keys

Coverage plans steer the build loop, verification, and export gates. They live in `workspace/coverage_plan.json` (or any path passed via `--plan-file`).

| Key | Purpose |
|---|---|
| `target_effective_count` | Required post-dedup record count. The build loop is not done until this is reached. |
| `group_minimums` | Single-axis bucket minimums keyed by metadata paths such as `metadata.subtopic`, `metadata.context_type`, `metadata.response_shape`, or `metadata.label`. |
| `max_share_per_group` | Mode-collapse ceiling for a single bucket. |
| `joint_group_rules` | Multi-axis rules with `fields`, optional `minimums`, and optional `max_share`. Useful for `difficulty x label` or `persona x response_shape`. |
| `required_fields` | Metadata or provenance paths every kept record must carry, e.g. `metadata.evidence_ids`, `metadata.reference_urls`. |
| `provenance` | Real-world grounding gate. Supports `minimum_real_world_share` and required `reference_fields`. |
| `response_length` | Caps median answer size and the share of oversized responses. |
| `response_structure` | Prevents one dominant JSON or text skeleton from taking over the corpus. |
| `response_prefix` | Repeated-opening cap using `prefix_length` and `max_share`. |
| `model_visibility` | Export-time sanitization rules for model-visible `instruction` and `context` (line-prefix removal, answer-bearing line drop, value redaction). Omit to apply a conservative built-in profile; set `"enabled": false` to disable. |
| `require_review_file` | When `true`, `build_loop.py` refuses to run without `--review-file`. |
| `class_balance` | Optional class-share targets for classification corpora. |
| `dpo` | DPO contrastive gates such as `min_pair_count` and `forbid_refusal_in_rejected`. |
| `review_requirements` | Structured review thresholds such as `min_capability_delta_score` and `require_grounding_pass`. |
| `research` | Research/evidence gates including `max_sources_per_domain`, `min_evidence_per_record`, and allowed source domains. |
| `grounding` | Grounding overlap thresholds enforced by `scripts/grounding.py` against `evidence.jsonl`. |

Advanced sections (`provenance`, `response_length`, `response_structure`, `response_prefix`) are warn-only by default. Set `blocking: true` inside a section to make it fail the build.

## Generic Requests

When the user types something like:

```text
generate a 1000-example customer support dataset
```

Treat it as a sized SFT generation request and produce:

- `workspace/canonical_train.jsonl`
- `workspace/canonical_test.jsonl`
- `workspace/DATA_CARD.md`

When the user types:

```text
audit this dataset
```

Treat it as a corpus-level quality assessment and produce:

- `workspace/AUDIT_REPORT.md`

For deeper command guidance, see [[Generation Workflow]] and [[Datasets and Exports]].
