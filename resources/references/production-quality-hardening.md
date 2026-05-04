# Production Quality Hardening

This reference describes optional gates for serious fine-tuning runs.

## Code quality

Enable `code_quality.enabled` to add AST-aware Python checks, JSON parsing, and delimiter/quote balance checks for JavaScript, shell, and SQL snippets.

## Code-aware deduplication

Use:

```bash
python3 scripts/dedup.py --from-status verified_pass --strategy code --threshold 0.92
```

For import-time duplicate rejection, use:

```bash
python3 scripts/generate.py --input drafts.jsonl --dedup-threshold 0.92 --dedup-strategy code
```

## DPO pair quality

Enable `dpo_audit.enabled` to reject empty/identical chosen-rejected pairs, refusal-like rejected responses, missing `metadata.dpo_delta`, implausibly short rejected responses, and excessive chosen/rejected length skew.

## Benchmark contamination

Enable `benchmark_contamination.enabled` to block common public-benchmark fingerprints. This is not a complete detector; it is a deterministic guardrail that forces re-drafting of suspicious records.

## Semantic review batching

Use `scripts/review_batch.py` to build a host-agent review prompt and validate review JSONL without requiring local scripts to call external LLM APIs.
