# seed-generator

Use this after `dataset-strategy`.

## Goal

Create or normalize draft records into the fixed canonical schema.

## Operating modes

### Topic-driven generation

**Research-first, synthesize-second (mandatory):**

Before drafting any synthetic record, the agent must research real-world material first:

1. **Search and collect real examples.** Use the IDE's browsing, search, and file-reading tools to find real-world instances of the target domain: forum posts, bug reports, documentation snippets, GitHub issues, StackOverflow threads, real conversation logs, CVE entries, or any authentic source relevant to the topic.
2. **Ground each record in a real scenario.** Every seed record should be traceable to a plausible real-world situation. Do not write abstract instructions like "Create example N for topic X." Instead, write instructions that a real user would actually type in a real tool.
3. **Use synthesis only for gap-filling.** After exhausting real-world sources, use synthesis to fill taxonomy buckets that have zero real-world coverage. Tag these with `metadata.source_origin: "synthetic"` and real-sourced ones with `metadata.source_origin: "real_world"`.
4. **Target ratio:** aim for at least 60% real-world-grounded records. If you cannot reach 60%, document why in the data card.

- Spread examples across taxonomy, persona, and difficulty.
- Keep records concrete and non-redundant.
- Unless the user specifies otherwise, target `500` total records.
- For large targets, generate in batches and keep going until the planned **effective** count is reached after duplicate suppression.
- Do not stop after a small starter set unless the user explicitly asked for a prototype or sample.

**Multi-constraint prompts (mandatory):** Every seed instruction must carry at least 2–3 explicit constraints, for example:
  - A *negative constraint*: "do not use the `requests` library", "avoid any markdown formatting"
  - A *format constraint*: "return only valid JSON", "respond in exactly 3 bullet points"
  - A *scoping constraint*: "assume the user is using Python 3.11", "the environment has no internet access"

Instructions with zero constraints are too easy and produce no fine-tuning signal. Re-draft them before writing the record.

**Blind Contexts / Information Asymmetry:** Ensure `<context>` blocks contain only raw, realistic inputs. Never leak the root cause, vulnerability mechanism, or explicit hints into the context before the assistant is forced to deduce it.

**Human imperfection injection (mandatory):**

Real users do not write perfectly formatted prompts. To avoid training a model that only responds well to polished inputs, deliberately vary instruction quality:

- **Typos and abbreviations** (10–15% of records): "pls check if vuln", "whats the issue w/ this func", "how do i fix teh error"
- **Incomplete context** (10–15%): truncated logs, missing HTTP headers, partial stack traces, redacted credentials
- **Ambiguous instructions** (5–10%): instructions that could be interpreted multiple ways, forcing the response to either clarify or make a stated assumption
- **Mixed formality** (spread across all): casual Slack-style messages, formal tickets, terse CLI-style one-liners, verbose newcomer questions
- **Copy-paste artifacts** (5%): extra whitespace, stray line numbers, terminal prompts left in, markdown that didn't render

Tag records with `metadata.instruction_fidelity` using values: `"polished"`, `"casual"`, `"messy"`, `"ambiguous"`.

**Response architecture variety (mandatory):**

Do not let every response follow the same skeleton. Force fundamentally different response shapes:

- **Concise direct answers** (15–25%): 1–3 sentences, no preamble, no steps.
- **Detailed walkthroughs** (20–30%): multi-paragraph with code, explanations, and caveats.
- **Socratic pushback** (5–10%): the expert questions the premise, asks for clarification, or explains why the question is wrong before answering.
- **Code-first responses** (10–20%): the response leads with code and follows with a brief explanation.
- **Disagreement or uncertainty** (5%): the expert says "I need more information" or "this depends on X" and explains why a single answer isn't possible.
- **Step-by-step reasoning with `<think>` blocks** (20–40% for reasoning tasks): but vary the depth and structure of the trace itself.

Tag records with `metadata.response_shape` using values: `"concise"`, `"walkthrough"`, `"socratic"`, `"code_first"`, `"uncertain"`, `"cot"`.

**Coverage metadata (mandatory for large or specialized datasets):**

To make generation steerable, annotate each record with the fields the coverage plan will track. At minimum, populate:

- `metadata.subtopic`
- `metadata.intent`
- `metadata.response_shape`
- `metadata.instruction_fidelity`
- `metadata.source_origin`

For specialized classification corpora, also populate:

- `metadata.context_type`
- `metadata.label`

Do not leave these to inference later. If the metadata is missing, the coverage script cannot tell what to generate next.

**Anti-trope guardrails:** Before finalising any response, scan for and remove:
  - Opening preambles: "As an AI…", "Certainly!", "Of course!", "Here is…", "Sure, here's…", "In summary"
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
For active generation runs, import with `--dedup-threshold 0.85` so near-duplicates are rejected before they distort the raw count.

For red-team, security, pentest, jailbreak, or prompt-injection datasets, treat injection-tolerant import as the default. Add `--enforce-security-flags` only when you want those payloads flagged instead of preserved.

## Required metadata

Each canonical record should carry enough metadata for later export and audit:

- `difficulty`
- `persona`
- `source_type`
- `subtopic`
- `intent`
- `response_shape`
- `instruction_fidelity`
- `source_origin`
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
