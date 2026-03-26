# diversity-engine

Use this when the base dataset is too narrow and needs broader coverage.

## Goal

Increase coverage without collapsing into duplicates.

## Apply variation across

**Surface axes (existing):**
- persona
- difficulty
- tone
- intent
- adversarial or tricky edge cases
- phrasing style

**Semantic axes (required — do not skip):**
- task category (e.g. code generation vs. code review vs. debugging)
- structural format (dense prose, pure code, Socratic dialogue, step-by-step numbered list)
- adversarial inputs (typos in the instruction, ambiguous phrasing requiring clarification, inherently contradictory requirements)
- user expertise level (novice making a category error vs. expert needing a subtle edge case)

## Coverage audit before augmentation

Before generating any variant, run a coverage audit:

1. Group existing records by intent/subtopic (use instruction keywords as a heuristic cluster key).
2. Count records per cluster. Flag any cluster with < 5% of total records as **undertopic**.
3. Flag any cluster with > 40% of total records as **mode collapse risk**.
4. Target augmentation at undertopics first. Do not create variants of already well-represented clusters unless undertopics are covered.
5. Count coverage on the **effective** corpus, not the raw corpus. Use `scripts/coverage.py` so near-duplicates do not hide missing buckets.

This prevents surface paraphrase of the easy/common case while rare edge cases stay at near-zero.

## Slot-filling matrix

For systematic capability coverage, plan augmentation using a matrix of:

```
task category × difficulty × user type × edge case type
```

Each cell should have at least one record. Cells that are empty after base generation are augmentation targets. Cells that already have 5+ records are low-priority.
For specialized datasets, set explicit per-cell minimums in a coverage plan and keep augmenting only the missing cells.

## Two execution paths

### Agent-authored augmentations

- Write fully rewritten canonical records to a file.
- Load them with:

```bash
python3 scripts/augment.py --input <augmented.jsonl> --tool-context <codex|claude|antigravity>
```

### Deterministic metadata variants

- Use when you want the pipeline to stamp variant rows first and rewrite them later.

```bash
python3 scripts/augment.py --from-status raw_generated --persona expert --persona reviewer --difficulty medium --difficulty hard
```

Important:
- Metadata-variant rows are scaffolding, not finished examples.
- The script now marks them `rewrite_required`.
- They will fail `verify.py` until the instruction/response has been genuinely rewritten.

## Guardrails

- **Ban "Mad-Libs" slot-filling**: Do not create variants that merely swap entity names or variable names while keeping the exact same reasoning structure.
- **Ban metadata-only completion**: Never count a metadata variant toward the requested dataset size until it has been rewritten and survives duplicate screening.
- **Enforce Structural Diversity**: Force the LLM to vary the entire reasoning pathway, paragraph structure, and code complexity.
- Keep semantic coverage wider than surface paraphrase.

## Anti-templating rules

When reviewing a batch of augmented records, apply these checks before finalising:

1. **Opening sentence test**: Extract the first sentence of every response in the batch. If more than 30% start with the same phrasing pattern (e.g., "The issue is…", "This code…", "To fix this…"), rewrite the repeating ones with different openings.
2. **Structure fingerprint test**: Classify each response as one of: `concise`, `walkthrough`, `socratic`, `code_first`, `uncertain`, `cot`. If any single shape exceeds 40% of the batch, rewrite extras into under-represented shapes.
3. **Length variance test**: Compute response lengths. If the standard deviation is less than 20% of the mean, the batch is too uniform. Intentionally make some responses much shorter and others much longer.
4. **Instruction naturalness check**: At least 20% of augmented instructions should read like a real person typed them — with casual grammar, abbreviations, or slight ambiguity. Do not polish every instruction into a formal prompt.
