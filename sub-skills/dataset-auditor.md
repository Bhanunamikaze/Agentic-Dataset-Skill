# dataset-auditor

Use this when the user wants to audit the quality, coverage, or integrity of an existing or freshly generated dataset.

This sub-skill orchestrates the existing quality tools and adds three higher-level checks that none of the individual sub-skills cover on their own.

---

## When to invoke

- The user says "audit my dataset", "check my dataset", "evaluate this JSONL", "how good is this dataset" or similar.
- After a full generation run, as a final quality gate before deployment.
- When re-evaluating a dataset weeks or months after it was generated.

---

## Phase 1 — Record-level audit (delegate to existing sub-skills)

Run these in order and collect results before drawing any conclusions.

### 1A. Structural validation
Read `sub-skills/data-verifier.md`. Run:

```bash
python3 scripts/generate.py --input <dataset.jsonl> --source-type raw_dataset --tool-context <context>
python3 scripts/verify.py --from-status raw_generated --source-run-id <run_id>
```

Capture the `verified_fail` count and all `heuristic_errors` strings from the report.

### 1B. Deduplication check
Read `sub-skills/deduplicator.md`. Run:

```bash
python3 scripts/dedup.py --from-status verified_pass --source-run-id <run_id>
```

Report the percentage of records removed. Flag if > 10% of records were duplicates.

### 1C. Semantic quality scoring
If the dataset is small enough (< 1000 records), read `sub-skills/llm-judge.md` and sample-score 10–15% of records. Report average judge score and the ratio of fail/pass at various score thresholds.

### 1D. Distribution summary
Run:

```bash
python3 scripts/export.py --format openai --split 0.1
```

Read the `workspace/DATA_CARD.md` that is produced. Extract:
- `difficulty_distribution` — flag if any single difficulty bucket > 60% of records
- `persona_distribution` — flag if any single persona > 50% of records
- `task_type_distribution` — flag if only one task type is present

---

## Phase 2 — Corpus-level audit (new checks beyond individual sub-skills)

These checks require reasoning across the full corpus, not individual records.

### 2A. Split disjointness audit

Objective: Verify the train split and test split have zero overlapping scenario fingerprints.

Steps:
1. Load both `workspace/canonical_train.jsonl` and `workspace/canonical_test.jsonl`.
2. For each record, compute the cluster key using the same logic as `scripts/export.py`: check `metadata.scenario`, `metadata.topic`, `metadata.intent`, `metadata.subtopic`, `metadata.fingerprint` in order; fall back to first 6 stemmed words of the instruction.
3. Compute `train_keys ∩ test_keys`.
4. **Pass**: intersection is empty. **Fail**: flag every overlapping key and the count of affected records.

### 2B. Taxonomy coverage audit

Objective: Verify that the dataset covers all planned taxonomy buckets, not just the most common ones.

Steps:
1. Look for any planning document or taxonomy definition (e.g., generated during `dataset-strategy`). If none exists, infer the intended taxonomy by clustering records by their metadata topic/intent keys.
2. Identify any taxonomy bucket that has **zero records** in the final verified corpus.
3. Identify any cluster with **fewer than 3 records** — these are thin-coverage buckets that will not provide meaningful gradient signal.
4. Report: zero-coverage buckets, under-covered buckets, and the top-3 most over-represented clusters.

### 2C. Context leakage detection

Objective: Verify that the `context` field does not reveal the answer, mechanism, or root cause that the `response` is supposed to deduce.

Steps:
1. Sample 20% of records (or all records if < 200 total).
2. For each sampled record, check whether any key tokens from the final verdict or root cause in `response.text` appear verbatim in `context`. Use a simple substring match on the most distinctive tokens.
3. Flag records where > 2 decisive tokens from the response appear literally in the context.
4. Report the leaked-context rate. If > 15% of sampled records show leakage, this is a **High severity** finding.

### 2D. Reasoning variety audit

Objective: Detect "slot-filling" — examples that appear diverse on the surface but share an identical reasoning structure.

Steps:
1. Extract the first sentence of each response and the overall structural shape (numbered list vs. prose paragraph vs. code block vs. `<think>` trace).
2. Group records by structural shape. Flag if > 50% of all records share the exact same shape.
3. Within each structural group, check if the first 10 content-bearing words of responses follow the same template. Flag clusters where > 3 consecutive records open with the same phrasing.
4. If > 40% of records are structurally identical, severity is **High**. If 20–40%, **Medium**.

### 2E. Quantity adequacy check

Objective: Verify that the total record count is sufficient for meaningful gradient signal given the task type.

Minimum thresholds (flag if below):

| Task type | Minimum records | Recommended |
|-----------|----------------|-------------|
| SFT classification (binary) | 200 | 500+ |
| SFT classification (multi-label) | 500 | 1000+ |
| SFT open-ended generation | 300 | 1000+ |
| DPO preference pairs | 500 | 2000+ |
| Specialized domain fine-tune | 1000 | 5000+ |

Report the count against the appropriate threshold. Flag as **High** if below minimum, **Medium** if below recommended.

### 2F. Statistical balance and randomness check

Objective: Verify that no combination of metadata attributes is so dominant that it will bias the model.

Steps:
1. For every pair of metadata axes (e.g., `difficulty × persona`, `difficulty × task_type`), compute a joint distribution table.
2. Flag any cell in the joint table that holds > 30% of total records.
3. Run a simple balance test: compute the coefficient of variation (CV = std / mean) across all buckets in each single-axis distribution. CV < 0.2 is well-balanced; CV 0.2–0.5 is moderate skew; CV > 0.5 is severe skew. Flag severe skew as **Medium**.
4. Check ordering: if records were generated in batches, check that the exported JSONL is shuffled. Records should not be monotonically ordered by `metadata.topic` or `metadata.difficulty`. If sorted order is detected, flag as **Low** (export script should shuffle).

### 2G. Response length calibration check

Objective: Verify that response lengths are appropriate for their task type — concise for classification, thorough for generation/CoT.

Steps:
1. Group records by `metadata.reasoning_style` (`chain_of_thought` vs. `direct`) and by inferred task complexity (simple factual vs. multi-step).
2. Compute median response length (in characters) per group.
3. Flag as **Medium** if:
   - A direct/classification response exceeds 800 characters (likely padding or over-explanation).
   - A chain-of-thought response is shorter than 300 characters (likely a truncated or missing trace).
4. Flag as **Low** if overall response length variance (std/mean) is < 0.2 — too uniform, likely over-templated.

### 2H. Label balance check (classification tasks)

Objective: For datasets where the response is a fixed label set, verify that positive and negative classes are balanced.

Steps:
1. Detect if the dataset is a classification task: look for `metadata.task_type = "classification"`, or if `response.text` contains only values from a small fixed set (e.g., "VULNERABLE"/"NOT_VULNERABLE", "PASS"/"FAIL", "YES"/"NO").
2. If classification is detected, compute the class distribution.
3. Flag as **High** if any single class exceeds 75% of records (severe imbalance that will cause a biased model).
4. Flag as **Medium** if any class is between 60–75% (moderate imbalance).
5. Recommend oversampling the minority class or regenerating records for under-represented labels.

---

### 2I. Synthetic fingerprint detection

Objective: Detect telltale signs that the dataset is LLM-generated rather than grounded in real-world scenarios.

Steps:
1. Sample 25% of records. For each, check for these synthetic markers:
   - **Uniform sentence length**: compute the standard deviation of sentence lengths within the response. Real writing has high variance; LLM output tends toward uniform mid-length sentences.
   - **Over-polished instructions**: if > 80% of instructions are grammatically perfect, formal, and complete sentences, this is a red flag. Real users write messy.
   - **Formulaic openings**: count how many responses start with "The", "This", "To", "In order to", or "Here". If > 50%, flag as templated.
   - **Missing `metadata.source_origin`**: if no records have `source_origin: "real_world"`, the dataset was likely 100% synthesized.
2. Compute a **synthetic score** (0–100): percentage of sampled records exhibiting 2+ synthetic markers.
3. Flag as **High** if synthetic score > 70%. **Medium** if 40–70%.

### 2J. Real-world grounding ratio check

Objective: Verify the dataset meets the planned real-world grounding target.

Steps:
1. Count records with `metadata.source_origin == "real_world"` vs. `"synthetic"`.
2. Compare against the planned ratio from the strategy document (default target: 60% real-world).
3. Flag as **Medium** if real-world ratio is below 40%. Flag as **Low** if between 40–60%.
4. If `metadata.source_origin` is missing from all records, flag as **Medium** — the provenance is untraceable.

---

## Phase 3 — Structured audit report

After all phases, produce a structured summary. Do **not** just emit raw numbers; classify each finding by severity.

```
## Dataset Audit Report

**Total records reviewed**: N
**Records passing structural checks**: N (X%)
**Duplicate rate**: X%
**Average judge score**: X / 10 (sampled)
**Real-world grounding ratio**: X%

### Findings

| # | Severity | Check | Detail |
|---|----------|-------|--------|
| 1 | High     | Split disjointness | 7 scenario fingerprints appear in both train and test |
| 2 | High     | Context leakage | 22% of sampled records expose the answer in context |
| 3 | High     | Label balance | "VULNERABLE" = 82% of corpus, "NOT_VULNERABLE" = 18% |
| 4 | High     | Synthetic fingerprint | synthetic score = 78%, dataset reads as LLM-generated |
| 5 | Medium   | Taxonomy coverage | 4 planned buckets have zero records |
| 6 | Medium   | Quantity adequacy | 180 records found, minimum for DPO is 500 |
| 7 | Medium   | Reasoning variety | 68% of responses share identical numbered-list structure |
| 8 | Medium   | Grounding ratio | 0% real-world sourced records, 100% synthetic |
| 9 | Low      | Balance/randomness | difficulty CV = 0.6, severe skew toward "medium" |
|10 | Low      | Response length | CoT responses avg 210 chars — likely truncated traces |

### Recommendations

For each High or Medium finding, emit a concrete, actionable fix:
- "Re-run export with `--split 0.2` and verify cluster disjointness."
- "Re-generate the 4 missing taxonomy buckets using `diversity-engine`."
- "Strip explicit answer tokens from context fields in records flagged for leakage."
- "Generate 320 more records to reach DPO minimum of 500."
- "Re-generate NOT_VULNERABLE examples to reach 40–60% class balance."
- "Research real-world scenarios and re-source at least 60% of records from authentic material."
- "Vary response openings and instruction formality to reduce synthetic fingerprint below 40%."
```

---

## Severity definitions

| Severity | Meaning |
|----------|---------|
| **High** | The dataset will likely produce a misleadingly optimistic eval score or a model that fails on real-world inputs |
| **Medium** | Reduces dataset utility; acceptable for a prototype but not for a training run |
| **Low** | Cosmetic or minor distribution skew; worth noting but not blocking |

## Deterministic audit command

Run the corpus audit script before the final handoff:

```bash
python3 scripts/audit.py --from-status verified_pass --report workspace/audit_report.json --markdown-report workspace/AUDIT_REPORT.md
```

When train/test canonical exports exist, include them:

```bash
python3 scripts/audit.py --train workspace/canonical_train.jsonl --test workspace/canonical_test.jsonl
```

The script checks split disjointness, source diversity, evidence linkage, label balance, taxonomy skew, response templating, and synthetic fingerprints.
