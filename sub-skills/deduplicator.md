# deduplicator

Use this after verification and before export.
For large generation runs, also use the same threshold earlier with `scripts/generate.py --dedup-threshold ...` so raw-count inflation is caught during import.

## Goal

Keep the strongest record in each duplicate cluster and suppress the rest.

## Policy

- Prefer the earliest or already-reviewed record as the keeper.
- Mark duplicates instead of silently dropping provenance.
- Run dedup on passing records before export.

## Deduplication levels

Run deduplication in two layers:

1. **Exact deduplication** (already implemented via SHA-256 hash in `scripts/dedup.py`): catches byte-for-byte copies.
2. **Semantic deduplication** (required for quality): catches records that ask the same conceptual question with different phrasing. Approach:
   - Represent each record as a token n-gram shingle set (already in `dedup.py` — threshold 0.85).
   - For larger datasets (> 1,000 records), the agent should flag clusters of semantically similar records by grouping instructions that share the majority of their keywords/phrases.
   - Preferred upgrade path: MinHash for scalable near-duplicate detection, or lightweight TF-IDF cosine similarity clustering if embeddings are unavailable.

## Sampling from clusters

When a semantic cluster contains more than one record, do not keep all of them. Instead:

1. Score all records in the cluster by their judge score (`judge_score` field).
2. Keep the record with the highest score. If scores are tied, prefer the one with the richest `context` field or the most explicit constraint in its `instruction`.
3. Mark all others as `deduped` — preserve provenance, do not delete.

The goal is one high-quality representative per semantic cluster, not one representative per phrasing variant.

## Prevention during generation

Do not wait until the end of the run to discover that 70% of the corpus collapses.

1. Import each generation batch with `scripts/generate.py --dedup-threshold 0.85`.
2. Run `scripts/coverage.py` on the active corpus.
3. Draft the next batch only for missing buckets or effective-count gaps.

## Command

```bash
python3 scripts/dedup.py --from-status verified_pass --threshold 0.85
```
