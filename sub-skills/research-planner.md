# research-planner

Use this before drafting records from web, URLs, local documents, or repositories.

## Goal

Create a research/evidence workspace before generation so records are grounded in traceable sources instead of generic search snippets.

## Required flow

1. Build a research plan with multiple subqueries, not a single broad query.
2. Collect sources with domain diversity and source-quality scoring.
3. Convert sources into evidence chunks.
4. Draft canonical dataset records from evidence chunks.
5. Put traceable provenance on every real-world record:
   - `metadata.evidence_ids`
   - `metadata.reference_urls`
   - `metadata.source_domain`
   - `metadata.source_quality_score`
   - `source_uri`

## Native command

```bash
python3 scripts/research.py \
  --query "<dataset topic or user request>" \
  --plan-file workspace/coverage_plan.json \
  --max-subqueries 12 \
  --max-results-per-query 8 \
  --tool-context codex
```

This writes:

- `research_plan.json` — subqueries and planner metadata
- `sources.jsonl` — fetched/scored sources
- `evidence.jsonl` — chunk-level evidence for record drafting
- `coverage_report.json` — domain/source/evidence coverage

## Optional GPT Researcher backend

Use only when the user explicitly wants deeper autonomous research and has installed optional dependencies/API keys:

```bash
python3 scripts/research.py --backend gpt_researcher --query "<topic>"
```

GPT Researcher is an optional backend, not the default. The base skill remains deterministic and tool-native.

## Record drafting contract

When converting evidence into canonical records:

- Do not copy chunks verbatim as assistant responses.
- Use evidence to create realistic user instructions and grounded assistant outputs.
- Keep answer-bearing labels/mechanisms in metadata when needed, then use `model_visibility` export rules to hide them from model-visible inputs.
- Each record marked `metadata.source_origin: "real_world"` should include at least one valid evidence ID.

## Research coverage checks

Coverage plans may include:

```json
{
  "research": {
    "minimum_unique_domains": 8,
    "max_share_per_domain": 0.25,
    "minimum_traceable_record_share": 0.8,
    "minimum_evidence_linked_share": 0.8,
    "minimum_source_quality_score": 0.6,
    "blocking": true
  }
}
```

Use these checks when the dataset will be used for training or evaluation, not just a prototype.
