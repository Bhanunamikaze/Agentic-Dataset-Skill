# agent-loop

Use this between batches to decide what to do next. Read `workspace/build_loop_progress.json` and the coverage output, then follow this decision tree before sending the next batch.

## After each batch

### Step 1 — Read progress

```bash
cat workspace/build_loop_progress.json
python3 scripts/status.py --db <db_path> [--plan-file <plan.json>]
```

Key fields to check:
- `complete`: if true → go to export step, stop generating
- `batches_done` / `batches_total`: how far along the session is
- `last_drift.drift_flag`: if true → a quality or coverage shift happened, investigate before next batch
- `last_drift.new_gaps`: new coverage gaps that opened up — target these in the next batch
- `last_drift.resolved_gaps`: gaps that closed — good signal

### Step 2 — Decide

| Condition | Action |
|---|---|
| `complete: true` | Run export, stop |
| `target_gap > 0` and bucket gaps exist | Draft next batch targeting the specific missing buckets |
| `drift_flag: true` | Read `new_gaps`, check why pass rate dropped; fix seed prompt before next batch |
| fail rate > 30 % | Run `judge_insights.py`, read `recommendations`, fix the top bucket before re-drafting |
| duplicate rate > 20 % | Increase persona/domain diversity in the seed prompt; lower `--dedup-threshold` to catch more near-dupes |
| 5+ batches processed with < 10 % improvement | Stop generating; audit the corpus and adjust the plan |

### Step 3 — Record lineage (optional but recommended)

```bash
python3 scripts/record_history.py --db <db_path> --note "after batch N"
```

This appends a snapshot to `workspace/record_history.jsonl` so you can compare effective counts across batches.

## Fail rate is high — fix by bucket

Run judge insights first:

```bash
python3 scripts/judge_insights.py --review-file <review.jsonl> --output workspace/judge_insights.json
```

Then act on the top bucket:

| Bucket | Fix in next seed prompt |
|---|---|
| `vague_instruction` | Add explicit constraints: word count, format, scope, persona |
| `weak_response` | Require minimum depth: "at least 3 paragraphs", "include an example" |
| `apology_opener` | Add: "Do not begin with an apology or 'I cannot'" |
| `trope_opener` | Add: "Do not open with 'Great question', 'Certainly', 'Of course'" |
| `refusal_error` | Rewrite instructions so the request is clearly in-scope |
| `grounding_fail` | Reference specific evidence IDs; require citations |
| `dpo_quality` | Ensure chosen/rejected are meaningfully different; populate `metadata.dpo_delta` |
| `format_violation` | State format requirements explicitly in the instruction |
| `leakage` | Strip answer-bearing lines from `context`; use `model_visibility` plan section |

## When to stop

Stop and move to export when any of these are true:
- `complete: true` in `build_loop_progress.json`
- The coverage plan is satisfied (all buckets at or above minimums, target effective count met)
- 5+ batches processed with less than 10 % new verified records added per batch
- The user says to stop

## Progress check commands

Run these after each batch to stay oriented:

```bash
# Quick status snapshot
python3 scripts/status.py --db workspace/<db>.sqlite --plan-file <plan.json>

# Coverage detail
python3 scripts/coverage.py --from-status verified_pass --db workspace/<db>.sqlite --plan-file <plan.json>

# Fail reason clustering (after semantic review)
python3 scripts/judge_insights.py --review-file workspace/review.jsonl

# Lineage snapshot
python3 scripts/record_history.py --db workspace/<db>.sqlite --note "batch N complete"
```

## Coverage templates

Pre-baked coverage plans live in `resources/templates/`:

| File | Use for |
|---|---|
| `production_quality_plan.json` | General SFT with full quality gates |
| `coverage_plan_classification.json` | Classification corpora |
| `coverage_plan_code_review.json` | Code review datasets |
| `coverage_plan_dpo_hard_negatives.json` | DPO contrastive pairs |
| `coverage_plan_multi_turn.json` | Multi-turn conversation datasets |
| `coverage_plan_fact_extraction.json` | Fact extraction with grounding |
| `coverage_plan_red_team.json` | Safety / red-team datasets |

## Reference examples

`resources/examples/` contains 5–6 high-quality canonical records per task type. Read the relevant file before drafting a new batch to calibrate instruction style, response depth, and metadata completeness.
