# dataset-strategy

Use this when the user asks to generate, normalize, or restructure a dataset.

## Goal

Turn the user request into a concrete dataset plan before any records are written.

## Required decisions

1. Classify the request:
   - Topic-driven synthetic dataset generation
   - URL or reference-material structuring
   - Existing dataset normalization
   - Verify-only audit
   - Export-only request
2. Choose `task_type`:
   - `sft` for single best answers
   - `dpo` for chosen/rejected preference pairs
3. Define the taxonomy:
   - domains, subtopics, personas, difficulty spread, edge cases
   - **Mandate Long-Tail Taxonomy Discovery:** explicitly research the full breadth of the domain to uncover rare, highly-specific edge cases and unique failure modes rather than settling for just the most common or obvious categories.
4. Define the target output:
   - OpenAI preset
   - HuggingFace preset
   - Flat CSV/JSONL
   - Custom schema file
5. Define the target example count:
   - use the user-provided size when present
   - default to `500` examples when the user does not specify a size
   - treat this as the **post-dedup effective count**, not the raw import count
6. Define coverage requirements before generation starts:
   - choose the metadata fields that will be used to track coverage, such as `metadata.subtopic`, `metadata.intent`, `metadata.context_type`, `metadata.response_shape`, `metadata.instruction_fidelity`, or `metadata.label`
   - set minimum counts for important buckets, especially minority classes and rare edge-case contexts
   - set a max-share threshold for mode collapse (default: 40% for any single bucket)
   - define `required_fields` for metadata or provenance that must never be missing on kept records
   - define `joint_group_rules` when single-axis balance is insufficient, for example `difficulty x label` or `persona x response_shape`
   - define provenance requirements such as minimum `real_world` share and traceable reference fields
   - define `response_length` limits when the task needs short or tightly bounded outputs
   - define `response_structure` limits when one JSON or text skeleton would otherwise dominate the dataset
   - define `response_prefix` limits when repeated openings or templated answer scaffolds are a risk
   - define `model_visibility` rules when labels, mechanisms, sink names, or other answer-bearing fields must remain in metadata for audit but should be stripped from model-visible `instruction` or `context`
   - choose which advanced quality sections are advisory versus blocking; by default these should stay advisory unless the user explicitly wants them enforced as hard completion gates
7. Decide ingestion safety mode:
   - red-team, security, pentest, jailbreak, and prompt-injection corpora should default to injection-tolerant import behavior
   - use strict flagging only when the user clearly wants defensive filtering instead
8. Choose a **platform profile** based on the target LLM:
   - *Codex*: prioritise raw code, inline comments, and FIM (Fill-in-the-Middle) structures; avoid conversational framing.
   - *Claude Code*: prioritise multi-turn agentic workflows, tool-use XML formatting (`<tool_use>`, `<result>`), and conversational clarification patterns.
   - *Antigravity*: prioritise general-purpose instruction-following, mixed formats, and diverse task types.
9. Apply **benchmark contamination guards**: during planning, explicitly avoid naming conventions, variable names, function names, and problem structures commonly found in HumanEval, MMLU, GSM8K, or MBPP. If the generated instruction resembles a known benchmark problem, re-draft it.
10. Define **sourcing strategy**:
   - **Research-first** (preferred): use IDE search, browsing, and file-reading to collect real-world scenarios before any synthesis. Set a target real-world grounding ratio (default: 60% real-sourced, 40% synthetic gap-fill).
   - **Synthesis-only**: acceptable only when the user explicitly asks for a fully synthetic dataset, or the domain has no publicly available real-world data. Document why real sourcing was skipped.
11. Decide batch size and steering loop:
   - generate in batches, not one monolithic pass
   - after each batch, import with `scripts/generate.py --dedup-threshold 0.85`
   - run `scripts/coverage.py` against the active corpus and draft the next batch only for the remaining coverage gaps

## Important rule

Do not hardcode one universal user-facing header layout.

- The canonical internal schema stays fixed.
- The final export schema is chosen per user request.
- If the user needs custom columns, create a schema file from `resources/templates/custom_flat_schema.json`.

## Output contract

Produce a concise plan with:

- request type
- task type
- source mode
- source type
- target format
- target schema or custom column list
- intended example count
- effective-count target and batch size
- taxonomy buckets
- coverage fields, per-bucket minimums, and max-share threshold
- required fields, joint-bucket rules, provenance rules, and response-prefix limits when needed
- quality requirements
- ingestion safety mode
- sourcing strategy and real-world grounding ratio
- resume or fresh-run decision

Always state the intended example count explicitly. Do not leave it implicit.

## Source-type mapping

- Topic-driven generation -> `generated`
- URL/reference-material structuring -> `url_reference`
- Existing dataset normalization -> `raw_dataset`
- Internet-research collection -> `internet_research`

Always state the chosen `source_type` explicitly before moving into the script layer.
