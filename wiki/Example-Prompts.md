# Example Prompts

Use these prompts when you want the dataset skill to run with clear scope, schema choice, coverage targets, and expected outputs. Replace placeholders such as `<topic>`, `<size>`, `<format>`, `<url>`, and `<keyword>` before running. The skill routes natural-language intent — explicit flags and `dataset <subcommand>` syntax are optional.

## Prompt Pattern

A strong dataset prompt usually includes:

- Target task: SFT instruction-tuning, DPO preference pairs, classification, refusal-handling, etc.
- Source mode: topic-driven synthesis, URL conversion, existing-dataset normalization, or web research.
- Size: explicit example count (omit to default to `500`).
- Export schema: OpenAI messages, HuggingFace chat, CSV, JSONL, or custom flat columns.
- Coverage constraints: groups, minimums, joint-axis rules, provenance, response shape.
- Quality gates: DPO contrastive gates, grounding overlap, review-file usage.

Example structure:

```text
Generate a <size>-example <task> dataset for <topic>.

Coverage:
- <axis 1> with <minimums or shares>
- <axis 2> with <minimums or shares>
- minimum real-world share: <0.0-1.0>

Export:
- <openai|huggingface|csv|jsonl|all> with <split>
- include DATA_CARD.md
```

## Basic SFT Generation

Use this for a straightforward topic-driven dataset.

```text
Generate a 1500-example customer support dataset.

Scope:
- Cover billing, account access, returns, shipping, technical troubleshooting, and policy questions.
- Include polite escalation, refusal-when-appropriate, and pushback-on-bad-asks samples.
- Vary tone: formal, casual, frustrated, multilingual remnants.

Export:
- OpenAI messages JSONL with a 10 percent test split.
- Produce DATA_CARD.md summarizing taxonomy, coverage, and known limitations.
```

Routing: `dataset-strategy.md` → `seed-generator.md` → `build_loop.py` → `verify.py` → `dedup.py` → `export.py`.

## Topic-Driven Generation With Edge Cases

Use this when long-tail coverage matters more than raw volume.

```text
Generate a 2000-example legal intake dataset for U.S. tenant-landlord disputes.

Coverage plan:
- subtopic minimums for habitability, security deposits, eviction notice, rent control, lease termination, repair requests, and retaliation claims
- joint rule: difficulty x jurisdiction (require both city-level and state-level scenarios)
- minimum real-world share: 0.6 with reference_fields metadata.evidence_ids and metadata.reference_urls
- response_prefix cap: prefix_length 12, max_share 0.05 (no repeated opening dominates)

Edge cases:
- ambiguous facts where the correct answer is "consult an attorney"
- adversarial users asking how to evade legal process (refuse with explanation)
- multi-step procedural questions (filing forms, deadlines)

Export:
- HuggingFace chat JSONL with 0.1 split
- include DATA_CARD.md
```

Routing: same as basic SFT, with `coverage.py` enforcing the plan during the build loop.

## URL-Driven Dataset Structuring

Use this when the user supplies reference URLs or local documents.

```text
Turn these URLs into a structured Q&A dataset for fine-tuning a documentation assistant.

URLs:
- https://docs.example.com/api/auth
- https://docs.example.com/api/webhooks
- https://docs.example.com/migration-guide

Goal:
- 400-800 instruction/response pairs grounded in the supplied pages.
- Each record must include source_uri, metadata.reference_urls, and metadata.source_domain.
- Reject any draft whose response is not supported by the source content.

Export:
- OpenAI JSONL with 0.1 split.
```

Routing: `local-collector.md` → `collect.py` (with `--urls`) → `seed-generator.md` drafts canonical records → `build_loop.py` → `verify.py` → `dedup.py` → `export.py`.

## Web-Research-Grounded Dataset

Use this for fintech, medical, cybersecurity, or any domain where real-world grounding matters.

```text
Use web research to build a 1200-example fintech compliance Q&A dataset.

Research:
- Use scripts/research.py with --max-sources-per-domain 5 to keep one site from dominating.
- Prefer regulator publications (sec.gov, finra.org, fca.org.uk), trade-press analysis, and reputable explainers.
- Reject low-quality SEO content and listicles.

Coverage:
- subtopic minimums: KYC/AML, suspicious activity reporting, market manipulation, consumer protection, data privacy, sanctions screening
- joint rule: jurisdiction x topic (US, EU, UK each represented)
- minimum_real_world_share: 0.7
- require_grounding_pass: true (responses must have >= 0.5 overlap with cited evidence)

Each record must include:
- metadata.evidence_ids
- metadata.reference_urls
- metadata.source_domain
- metadata.source_quality_score
- metadata.scenario_fingerprint

Export:
- HuggingFace chat JSONL with 0.1 split.
```

A similar prompt works for medical triage or red-team cybersecurity datasets — change the seed domains and the grounding sources.

Routing: `research-planner.md` → `research.py` writes `sources.jsonl` and `evidence.jsonl` → agent drafts canonical records with provenance → `build_loop.py` (with `--review-file`) → `verify.py` (with `grounding.py` gate) → `dedup.py` → `export.py`.

## DPO Preference Pairs With Hard Negatives

Use this for preference data with contrastive rejected responses.

```text
Generate a 1000-example DPO dataset for Python code review focusing on identifying subtle concurrency bugs. I will use this to train an LLM to act as an automated PR reviewer.

Each example should be structured as follows:
- Context: A snippet of Python code using asyncio or threading with a hidden race condition or deadlock.
- Instruction: "Please review this code for concurrency issues."
- Chosen Response: A <think> block with step-by-step reasoning that correctly identifies the root cause, followed by a polite explanation and fixed code.
- Rejected Response: A plausible-sounding review that misses the bug entirely or suggests a flawed "fix".

Coverage plan:
- subtopic minimums: asyncio cancellation, lock ordering, GIL assumptions, shared-state mutation, race-on-check, async-context misuse
- dpo.min_pair_count: 1000
- dpo.forbid_refusal_in_rejected: true
- dpo.min_pair_delta_chars: 200 (chosen and rejected must materially differ)
- response_length: cap median chosen length at 1500 chars, reject anything over 4000

Ensure the dataset covers diverse real-world scenarios like asynchronous task cancellation, shared state mutations, and improper lock ordering. Export the dataset in HuggingFace format.
```

Routing: `dataset-strategy.md` → `dpo-pair-generator.md` drafts contrastive pairs → `build_loop.py` (DPO mode) → `verify.py` with `dpo_quality.py` gates → `export.py`.

## Existing Dataset Normalization

Use this when the user already has a CSV or JSONL and wants it reshaped.

```text
Normalize this CSV into OpenAI JSONL chat format and deduplicate it.

Input: workspace/inbound/raw_support_tickets.csv

Mapping:
- "ticket_subject" + "ticket_body" -> instruction
- "agent_reply" -> response
- "category" -> metadata.subtopic
- "priority" -> metadata.difficulty

Cleanup:
- Reject rows with empty agent_reply.
- Run dedup at threshold 0.92 using the shingle strategy.
- Strip PII patterns (emails, phone numbers, full names) before export.

Export:
- OpenAI JSONL with 0.1 split.
- Include DATA_CARD.md describing the source corpus and cleanup decisions.
```

Routing: `data-verifier.md` → `generate.py --source-type raw_dataset` → `verify.py` → `dedup.py` (`--strategy shingle --threshold 0.92`) → `export.py --format openai`.

## Audit and Remediation Flow

Use this when the user wants a structured quality assessment of an existing or freshly generated dataset.

```text
Audit this dataset for leakage, synthetic patterns, and coverage gaps.

Input: workspace/canonical_train.jsonl and workspace/canonical_test.jsonl

Required checks:
- train/test disjointness on canonical_text and on metadata.scenario_fingerprint
- context-leakage scan (do response tokens leak into instruction context across the split?)
- response-prefix repetition with prefix_length 16, max_share 0.05
- joint-bucket skew on persona x response_shape
- provenance verification: every real-world record must include metadata.evidence_ids and metadata.reference_urls
- benchmark-contamination scan against HumanEval, MBPP, GSM8K, and MMLU fingerprints

Output:
- workspace/AUDIT_REPORT.md grouped by severity (Critical, Warning, Info).
- For every finding, include affected_record_count, sample_ids, and a recommended remediation.
- Do not treat a missing optional field as Critical.

After the audit, propose a remediation plan with specific batch retargets if any bucket fails its minimum.
```

Routing: `dataset-auditor.md` → `audit.py` → `verify.py` → `dedup.py` → `quality_report.py` → final structured report.

## Adversarial / Red-Team Dataset

Use this for prompt-injection, jailbreak, system-prompt-leak, or red-team SFT corpora.

```text
Generate red-team prompt-injection training data with 800 examples.

Goal:
- Each record contains a hostile user prompt designed to override the assistant's system instructions, plus a labeled "safe response" that refuses or redirects.
- Cover obfuscation techniques: base64, leetspeak, indirect references, role-play framings, multilingual injections, system-prompt-leak baits.
- Include benign-looking adversarial prompts that should still trigger refusal.

Pipeline rules:
- Use injection-tolerant import (the scripts auto-enable this; pass --allow-injections for clarity).
- Do NOT flag the hostile content itself with metadata.requires_manual_review.
- Run normal control-character cleanup and canonicalization.
- Refusal regex must NOT downgrade the safe responses as low quality — they should validate as verified_pass.

Coverage:
- group_minimums on metadata.injection_technique (10 techniques)
- joint rule: injection_technique x target_field (system_prompt vs tool_call vs response_format)

Export:
- JSONL with 0.0 split (keep all for training).
```

Routing: `dataset-strategy.md` → `seed-generator.md` → `generate.py --allow-injections` → `verify.py` (which exempts records with `metadata.label=refusal` from refusal-regex penalties) → `dedup.py` → `export.py`.

## Custom Flat Schema Export

Use this when downstream tooling expects specific column names.

```text
Export the verified dataset with custom CSV columns: prompt, answer, persona, difficulty, source_domain.

Source: existing verified_pass records in SQLite from run id <run_id>.

Mapping:
- prompt        <- instruction
- answer        <- response.text
- persona       <- metadata.persona
- difficulty    <- metadata.difficulty
- source_domain <- metadata.source_domain

Split: 0.1 test split. Output CSV with a UTF-8 BOM for Excel compatibility.

Include DATA_CARD.md describing field provenance and any redactions.
```

Routing: `formatter-exporter.md` → write/update schema file from `resources/templates/custom_flat_schema.json` → `export.py --format csv --schema-file <path> --split 0.1`.

A Python-equivalent schema file:

```json
{
  "name": "support-export",
  "mode": "flat",
  "columns": [
    {"name": "prompt", "source": "instruction"},
    {"name": "answer", "source": "response.text"},
    {"name": "persona", "source": "metadata.persona"},
    {"name": "difficulty", "source": "metadata.difficulty"},
    {"name": "source_domain", "source": "metadata.source_domain"}
  ]
}
```

## Verify-Only Cleanup

Use this when the user has a freshly generated file and wants the heuristic + dedup pipeline.

```text
Verify and clean this dataset, then export it with custom CSV headers.

Input: workspace/inbound/draft_tickets.jsonl

Run:
- import with --source-type raw_dataset
- run scripts/verify.py with the supplied review.jsonl
- run scripts/dedup.py at threshold 0.88
- export CSV with the custom schema in workspace/schemas/support_csv.json
- include DATA_CARD.md
```

Routing: `data-verifier.md` → `generate.py` (DB-backed import) → `verify.py` → `dedup.py` → `export.py`.

## Generic Sized Generation (No Other Constraints)

When the user does not specify a size, target `500` records:

```text
Generate a code-review dataset for Go.
```

The skill plans for `500` post-dedup records, drafts in batches, runs heuristic + review verification, dedups, and exports OpenAI JSONL by default with a 0.1 test split.

When the user asks for a sample or prototype:

```text
Make a 50-example prototype for medical triage so I can sanity-check the schema.
```

Then a smaller output is acceptable, and the agent skips the full coverage-plan enforcement.
