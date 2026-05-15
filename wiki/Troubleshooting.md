# Troubleshooting

Common failure modes from the build loop, verification, dedup, audit, and export stages. Each section names the symptom, the cause, and the deterministic fix. For the gates these errors originate from, see [[Generation Workflow]].

## SQLite database is locked

**Symptom:** `sqlite3.OperationalError: database is locked` from `generate.py`, `verify.py`, `dedup.py`, or `build_loop.py`.

**Cause:** Two or more pipeline scripts are running against the same `workspace/run_state.sqlite` at once.

**Fix:** Pass a unique `--db <path>` to each parallel run, or let `build_loop.py` create its own per-build database under `workspace/build_loop_build_<hash>.sqlite`.

## "raw collected source chunk must be converted into a training example before verification"

**Symptom:** `verify.py` rejects records that were just imported from a collect run.

**Cause:** The records came directly from `scripts/collect.py` (`pipeline_status: collected`). Raw collected chunks are source material, not training examples.

**Fix:** Read the collected JSONL, draft canonical instruction/response records from it, and re-import with `python3 scripts/generate.py --input <drafts.jsonl> --source-type url_reference`.

## "response matched refusal pattern" on legitimate content

**Symptom:** A perfectly good response is rejected with the refusal-regex gate.

**Cause:** The response opens with phrasing that the refusal anchor catches (`"I cannot help with"`, `"I am unable to"`, etc.).

**Fix (Phase 14):** The regex now anchors to the first 200 characters, so refusals mid-response no longer trigger. If the dataset is intentionally *about* refusals or safety, set `metadata.label: "refusal"` (or `metadata.intent` to a refusal-aligned value) and the record will be exempt from the gate.

## "response begins with trope opener"

**Symptom:** Records fail with `response begins with trope opener` during verification.

**Cause:** The coverage plan enables `quality_filter.anti_trope: true` (or the gate is auto-on) and the response starts with a templated LLM phrase such as `"As an AI"`, `"Certainly!"`, `"Sure, here is"`, or `"I'd be happy to"`.

**Fix:** Rewrite the response to begin with substantive content. Drop the chatbot preamble. The same record will pass once the trope opener is gone.

## "real-world/grounded record is missing metadata.evidence_ids"

**Symptom:** Verification fails for records marked `metadata.source_origin: real_world`.

**Cause:** A real-world record has no traceable evidence chain. The pipeline requires real-world records to link back to `evidence.jsonl`.

**Fix:** Add the relevant evidence IDs from `workspace/research/evidence.jsonl` to `metadata.evidence_ids`, or change `metadata.source_origin` to `synthetic`/`hybrid` if the record is no longer grounded in real evidence.

## "low response/evidence lexical overlap: 0.xxx < 0.200"

**Symptom:** `grounding.py` rejects a record whose response cites evidence.

**Cause:** Phase 14 raised the minimum response/evidence overlap floor to `0.20`. The response references the evidence but the lexical overlap (after stopword filtering) is too low.

**Fix:** Rewrite the response to incorporate evidence wording — quote, paraphrase tightly, or reuse named entities. If you intentionally want lower overlap, lower `grounding.minimum_response_evidence_overlap` in the coverage plan.

## "Playwright not installed" when calling `browser_collect.py`

**Symptom:** `browser_collect.py` exits with `Playwright not installed` or `chromium not found`.

**Fix:** Install the optional browser dependencies:

```bash
pip install -r requirements-browser.txt
playwright install chromium
```

## Schema validation errors after `dataset verify`

**Symptom:** `verify.py` reports schema errors on records that were freshly imported from a flat file.

**Cause:** The source file contains fields outside the canonical record shape (`id`, `task_type`, `instruction`, `context`, `response`, `metadata`, `pipeline_status`).

**Fix:** Normalize through `scripts/generate.py --source-type raw_dataset` before running verify. The generate step maps non-canonical fields into `metadata.*` and validates the result against `resources/internal-schema/canonical_schema.json`.

## Train/test split leakage flagged by `scripts/audit.py`

**Symptom:** `audit.py` reports `split_disjointness` findings — the same `scenario_fingerprint` appears in both `canonical_train.jsonl` and `canonical_test.jsonl`.

**Cause:** Records drafted from the same evidence chunk inherited the chunk's identity but did not copy `metadata.scenario_fingerprint`, so the splitter could not deduplicate them.

**Fix:** Copy `scenario_fingerprint` from `evidence.jsonl` onto every drafted record. Re-run the export to regenerate splits.

## "DPO chosen response looks like a refusal"

**Symptom:** A DPO record fails verification with `chosen response looks like a refusal`.

**Cause (Phase 14):** The chosen side of the preference pair contains refusal language. The preferred response cannot itself be a refusal — that would teach the model the wrong behaviour.

**Fix:** Regenerate the chosen response so it demonstrates the target capability. The rejected response can still be the refusal.

## High "Cluster fallback overuse" finding in the audit report

**Symptom:** `AUDIT_REPORT.md` lists a high cluster-fallback rate.

**Cause:** Too many records lack `metadata.scenario_fingerprint`, `metadata.topic`, or `metadata.evidence_ids`, so the audit falls back to clustering them by instruction-word similarity.

**Fix:** Add at least one of `scenario_fingerprint`, `topic`, or `evidence_ids` to records that are missing all three. This gives the auditor a real cluster key and removes the fallback warning.

For workflow context behind any of these gates, see [[Generation Workflow]] and [[Datasets and Exports]].
