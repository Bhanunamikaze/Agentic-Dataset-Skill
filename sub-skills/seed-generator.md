# seed-generator

Use this after `dataset-strategy`.

## Goal

Create or normalize draft records into the fixed canonical schema.

## Operating modes

### Topic-driven generation

- Draft canonical records directly in JSONL.
- Spread examples across taxonomy, persona, and difficulty.
- Keep records concrete and non-redundant.
- Unless the user specifies otherwise, target `500` total records.
- For large targets, generate in batches and keep going until the planned count is reached.
- Do not stop after a small starter set unless the user explicitly asked for a prototype or sample.

**Multi-constraint prompts (mandatory):** Every seed instruction must carry at least 2–3 explicit constraints, for example:
  - A *negative constraint*: "do not use the `requests` library", "avoid any markdown formatting"
  - A *format constraint*: "return only valid JSON", "respond in exactly 3 bullet points"
  - A *scoping constraint*: "assume the user is using Python 3.11", "the environment has no internet access"

Instructions with zero constraints are too easy and produce no fine-tuning signal. Re-draft them before writing the record.

**Anti-trope guardrails:** Before finalising any response, scan for and remove:
  - Opening preambles: "As an AI…", "Certainly!", "Of course!", "Here is…", "Sure, here’s…", "In summary"
  - Self-referential hedges: "As a language model…", "I should note that…"
  - Filler closings: "I hope this helps!", "Let me know if you need anything else."

Drop these entirely. The response should start with the actual content.

### URL or reference-material structuring

- Use available browsing, file-reading, and search tools in the IDE.
- Extract facts, examples, or source passages.
- Convert them into canonical records instead of copying raw source dumps.
- If the user does not specify size, aim for `500` structured records by default.

### Existing dataset normalization

- Map source columns into canonical fields.
- Preserve provenance in metadata.
- Keep the source URI/path when available.
- Preserve as much of the usable dataset size as possible unless the user asks for sampling.

## Output path

Write draft records to a JSONL file, then load them with:

```bash
python3 scripts/generate.py --input <drafts.jsonl> --source-type <generated|url_reference|raw_dataset|internet_research> --tool-context <codex|claude|antigravity>
```

The imported drafts will enter the pipeline as `raw_generated` records unless they still contain explicit placeholder responses, in which case they remain `seeded`.

For red-team, security, pentest, jailbreak, or prompt-injection datasets, treat injection-tolerant import as the default. Add `--enforce-security-flags` only when you want those payloads flagged instead of preserved.

## Required metadata

Each canonical record should carry enough metadata for later export and audit:

- `difficulty`
- `persona`
- `source_type`
- optional provenance such as `reference_urls`, tags, source path, or notes

For untrusted imports and web-derived material, also inspect:

- `metadata.security_flags`
- `metadata.requires_manual_review`

## Multi-turn conversation records

For agentic workflows (Claude Code, Antigravity, tool-use), single-turn records are insufficient. Use the following encoding for multi-turn conversations:

- `context`: the full conversation history up to (but not including) the final user turn, formatted as alternating `User:` / `Assistant:` blocks.
- `instruction`: the final user turn (the message the model must respond to).
- `response.text`: the ideal assistant response for that final turn.

Examples of when to use multi-turn records:
- Tool-use sequences where the model must call a tool and incorporate its result.
- Clarification dialogues where the model asks a follow-up before answering.
- Agentic tasks that require re-planning mid-conversation.

Tag these records with `metadata.format: "multi_turn"`.

## Chain-of-thought & reasoning traces

For code tasks, math, logic puzzles, and planning problems include a reasoning trace before the final answer. Use this format in `response.text`:

```
<think>
Step-by-step reasoning here...
</think>

Final answer or code here.
```

Use `metadata.reasoning_style: "chain_of_thought"` when a reasoning trace is present, and `"direct"` when the response is a straight answer. Aim for a mix — roughly 40–60% chain-of-thought for code/reasoning tasks, 10–20% for factual/retrieval tasks.

## Seed-only fallback

If you only need placeholder slots before writing full examples:

```bash
python3 scripts/generate.py --topic "<topic>" [--count <n>] --task-type <sft|dpo>
```

If `--count` is omitted, the placeholder target defaults to `500`.
