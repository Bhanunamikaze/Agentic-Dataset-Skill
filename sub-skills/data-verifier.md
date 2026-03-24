# data-verifier

Use this when the user already has a dataset file and wants an audit instead of generation.

## Flow

1. Normalize/import the file:

```bash
python3 scripts/generate.py --input <dataset.jsonl_or_csv> --source-type raw_dataset --tool-context <codex|claude|antigravity>
```

Capture the `run_id` from the output and reuse it in the next steps.

2. Run heuristic verification and, if needed, attach a review file:

```bash
python3 scripts/verify.py --from-status raw_generated --source-run-id <run_id> --review-file <review.jsonl>
```

3. Deduplicate passing records:

```bash
python3 scripts/dedup.py --from-status verified_pass --source-run-id <run_id>
```

4. Export audit-ready outputs:

```bash
python3 scripts/export.py --format csv --split 0.0 --source-run-id <run_id>
```

## Audit focus

- schema conformity
- label consistency
- refusal leakage
- duplicate rate
- exportability into target formats
