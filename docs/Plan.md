# Implementation Plan — Remaining Research/Evidence Pipeline Gaps

> Status as of 2026-05-05: the analysis pass that produced the original Plan
> recommended 15 issues across 5 phases. Phases 0–5 are committed (`a3fbdc2`
> through `5a4a248`) and the 50-test suite passes. This document tracks the
> work that is **still required** based on a code-level audit of the merged
> phases, plus items that have been intentionally **deferred** or **dropped**.

## How to use this document

You are Sonnet, asked to finish the remaining items. Work top-down: Task 1
(tests) is the highest priority because it gates regressions on everything else
that has already shipped. Each task below specifies:

- **Files to edit / add** — exact paths.
- **Public surface** — function signatures, CLI flags, plan keys.
- **Behavior** — what must be true after the change.
- **Tests** — concrete cases to add to `tests/test_pipeline.py`.

Do not modify behavior outside the listed files unless a test forces it.

After each task, run `python3 -m pytest tests/ -x -q` and ensure it stays green.
Commit per task using the existing phase-style message format
(`Phase 6: <short summary>`, `Phase 7: ...`, etc.).

---

## Done — do not redo

The following items from the original analysis are already implemented and
covered by the existing tests or by manual smoke runs in the recent commits.
Confirm by reading the file before re-touching:

- `scripts/research.py` with `--backend native|gpt_researcher`, planner,
  per-subquery search, source quality scoring, URL canonicalization/dedup,
  evidence chunking, `research_plan.json`, `sources.jsonl`, `evidence.jsonl`,
  `coverage_report.json`.
- `scripts/grounding.py` with `--evidence-file`, lexical overlap check, and
  `--from-status`/`--input` modes.
- `scripts/audit.py` with split disjointness, taxonomy, source diversity,
  label balance, and synthetic fingerprint findings; emits both
  `audit_report.json` and `AUDIT_REPORT.md`.
- `scripts/utils/research_plan.py`, `source_quality.py`, `source_dedup.py`.
- `scripts/utils/web.py`: `is_url_fetchable` blocks localhost/private/loopback,
  enforces `http(s)`; `search_web_all_backends` aggregates across backends and
  deduplicates by URL.
- `scripts/verify.py`: `--evidence-file`, `--require-evidence`,
  `task_relative_errors`, `syntax_errors` (Python `ast.parse` + JSON), refusal
  pattern set, status=`collected` guard, extended review fields
  (`structural_pass`, `instruction_following_pass`, `grounding_pass`,
  `format_pass`).
- `scripts/coverage.py`: `compute_research_coverage` (unique domains,
  per-domain share, evidence-linked share, source-quality minimum, blocking).
- `scripts/dedup.py`: `--strategy {shingle,tfidf,minhash}` CLI flag plumbed into
  `find_duplicates`. `tfidf` is real; `minhash` currently aliases shingle —
  see Task 4.
- `sub-skills/research-planner.md`, updates to `dataset-auditor.md`,
  `seed-generator.md`, `quality-filter.md`, `llm-judge.md`.
- `SKILL.md` and `docs/workflows.md` describe the research/evidence flow and
  the optional GPT Researcher backend; `requirements-research.txt` exists.

If any of those is broken for the user's specific input, fix it — but do not
rewrite a working module just to "modernize" it.

## Deferred / dropped (do not implement unless asked)

These were in the original 15-issue list but should stay out of scope:

- Optional SQLite tables `sources`, `evidence_chunks`, `record_evidence_links`
  from Issue #3. The JSONL artifacts plus `metadata.evidence_ids` already give
  us auditability without a schema migration. Skip.
- `--respect-robots` from Issue #14. The original analysis marked it optional;
  it adds operational complexity for a niche case. Skip.
- Vendoring GPT Researcher into the repo (Issue #7). Stay opt-in via
  `requirements-research.txt`. Skip.
- Embedding-based dedup strategy. Adds a heavyweight optional dep without a
  clear request. Skip — the `tfidf` strategy is good enough as the strong
  fallback.

---

## Task 1 — Tests for the new research/evidence pipeline (BLOCKING)

**Why first.** Issue #15 was real: the new modules ship with zero direct test
coverage. Today the suite is 50 tests, none of them touch
`scripts/research.py`, `grounding.py`, `audit.py`, or the new utilities. Until
the tests exist, every later change is a regression risk.

### Files to edit

- `tests/test_pipeline.py` — add new test classes; do not delete existing ones.
- (Optional) `tests/conftest.py` — add small fixtures only if the same setup
  is repeated more than three times.

### Test classes to add

Use the existing test style in `tests/test_pipeline.py` (subclass
`unittest.TestCase`, use temp dirs, no network). Write each test so it runs in
under 100 ms — no real HTTP, no real search backends. Mock at the function
boundary: monkeypatch `scripts.utils.web.fetch_url`,
`scripts.utils.web.search_web_all_backends`, and
`scripts.utils.web.extract_text` to return canned fixtures.

#### 1A. `ResearchPlannerTests`

Test `scripts.utils.research_plan.build_research_plan`:

1. With only `query="prompt injection in LLM apps"` and no plan/taxonomy,
   the result has `subqueries[0].query == query` and at least 5 subqueries.
2. With a coverage plan containing `taxonomy: {"category": ["sql", "xss"]}`
   and a query, generated subqueries include both taxonomy values.
3. `max_subqueries=3` truncates the list to length 3.
4. Subquery IDs are stable, lowercase-deduplicated, and follow `rq_NNN` form.
5. Empty query + empty plan returns `{"subqueries": []}` without raising.

#### 1B. `SourceQualityTests`

Test `scripts.utils.source_quality`:

1. `domain_from_url("https://www.GitHub.com/foo")` returns `"github.com"`.
2. `classify_source_type("https://docs.python.org/3/library/json.html")`
   returns `"documentation"`; `github.com` returns `"code_or_issue_tracker"`.
3. `source_quality_score` for a `github.com` URL with a query-matched title
   and a 2 KB body scores higher than a generic blog URL with the same body.
4. `boilerplate_penalty("Subscribe! Cookie policy. Sign up.")` is positive
   and bounded by 0.35.
5. `source_distribution([...])` returns `unique_domains` and `domain_counts`
   sorted by descending count.

#### 1C. `SourceDedupTests`

Test `scripts.utils.source_dedup`:

1. `canonicalize_url("https://Example.com/Foo/?utm_source=x&a=1")` strips
   `utm_source` but keeps `a=1`, lowercases host, and removes trailing slash.
2. `canonicalize_url("https://example.com//foo//bar/")` collapses repeated
   slashes.
3. `dedupe_sources` keeps the first of two sources whose URLs differ only by
   tracking params; sets `canonical_uri`.
4. Non-HTTP URIs (e.g. `file:///etc/hosts` or a local path) are kept as-is by
   string equality.

#### 1D. `WebSafetyTests`

Test `scripts.utils.web.is_url_fetchable`:

1. `https://example.com` returns `True`.
2. `http://localhost`, `http://127.0.0.1`, `http://10.0.0.1`,
   `http://192.168.1.1`, `http://[::1]` all return `False` by default.
3. With `allow_private_network=True`, the private/loopback URLs return
   `True`.
4. `ftp://example.com` and `file:///etc/passwd` return `False`.
5. Empty / malformed strings return `False`.

#### 1E. `SearchAggregationTests`

Test `scripts.utils.web.search_web_all_backends`:

1. Monkeypatch the five backend functions
   (`_search_serpapi`, `_search_bing`, `_search_google_cse`,
   `_search_duckduckgo_lib`, `_search_duckduckgo_html`) so two of them return
   overlapping `SearchResult`s. Confirm the merged output dedupes by URL.
2. With `max_results=3`, the function stops at 3 unique results even when
   more are available.
3. When every backend raises, the function returns `[]` without raising.

#### 1F. `ResearchPipelineTests`

Test `scripts.research.run_native_backend` end-to-end against a temp
workspace, with all network functions monkeypatched:

1. Given a `--query` and a fake search backend returning two URLs, two fake
   `fetch_url` HTML payloads, and a fake `extract_text` that returns 2 KB of
   text, the run produces:
   - `research_plan.json` with non-empty `subqueries`
   - `sources.jsonl` with 2 rows whose `source_quality_score` is between
     0.0 and 1.0 and whose `domain` is set
   - `evidence.jsonl` with at least 2 chunks linked back to a `source_id`
   - `coverage_report.json` with `unique_domains == 2`
2. With `--snippets-only`, no `fetch_url` calls occur and evidence is built
   from the snippet text.
3. Local-mode (`--paths`) reads files from a temp dir, produces sources with
   `source_mode == "local_file"` and `domain == "local"`.
4. URL safety: a `--urls http://localhost/foo` source is recorded with
   `status == "error"` and `error == "url blocked by safety policy"`, and no
   evidence row is written for it.

#### 1G. `GroundingCheckTests`

Test `scripts.grounding.check_record`:

1. A record with `metadata.evidence_ids: ["ev_known"]` and a response that
   shares ≥ 8% tokens with the evidence chunk passes (`status == "pass"`).
2. A record missing `metadata.evidence_ids` fails with finding
   `"missing evidence_ids"`.
3. A record citing an unknown evidence ID fails with finding starting with
   `"unknown evidence_ids:"`.
4. A record whose response shares zero tokens with cited evidence fails with
   `"low response/evidence lexical overlap"` when the plan sets
   `grounding.minimum_response_evidence_overlap: 0.2`.

#### 1H. `AuditScriptTests`

Test `scripts.audit` helpers (don't shell out):

1. `taxonomy_findings` flags a Medium finding when one subtopic owns
   > 60% of records.
2. `source_findings` flags Medium when `< 50%` of records carry
   `metadata.evidence_ids`.
3. `label_balance` flags High when one label owns > 75% of classification-like
   records (≤ 3 words, ≤ 40 chars in `response.text`).
4. `synthetic_fingerprint` produces a synthetic score > 70 when 90% of
   responses share an identical 48-char opening.
5. `split_disjointness` flags High when the same cluster key appears in both
   train and test inputs (use temp JSONL files; reuse `get_cluster_key`).

#### 1I. `VerifyEvidenceAndCollectedTests`

Test `scripts.verify.heuristic_errors`:

1. A record with `status == "collected"` always returns the error
   `"raw collected source chunk must be converted into a training example
   before verification"`. (This is the Issue #4 guard — it must stay enforced.)
2. With `plan.research.minimum_evidence_linked_share` set,
   `metadata.source_origin == "real_world"`, and no `evidence_ids`, error
   includes `"missing metadata.evidence_ids"`.
3. With `--evidence-file` provided as a dict and a record citing a known
   evidence ID, no evidence-related error is produced.
4. `task_relative_errors` flags a `code_review` record whose response is
   < 50 words; passes a `classification` record with a 1-word label.
5. `syntax_errors` flags a Python ```python block``` containing
   `def f(:` as a syntax error; passes a valid `def f(): pass`.

#### 1J. `ResearchCoverageTests`

Test `scripts.coverage.compute_research_coverage`:

1. Records with two distinct domains and `research.minimum_unique_domains: 5`
   produces a finding `{"type": "unique_domains", ...}`.
2. Records where one domain holds 80% and `research.max_share_per_domain: 0.5`
   produces `{"type": "domain_concentration", ...}`.
3. With `research.minimum_evidence_linked_share: 0.8` and 50% of records
   missing `evidence_ids`, finding `{"type": "evidence_linkage", ...}`.
4. `minimum_source_quality_score` flags low-score records.

### Acceptance criteria

- New tests pass in isolation and as part of the full suite.
- Total test count rises from 50 to ≥ 90.
- No real network or subprocess calls in any new test.
- `python3 -m pytest tests/ -x -q` finishes in under 15 s on a clean machine.

---

## Task 2 — DPO-specific deterministic checks (Issue #11)

**Why.** `verify.py` walks `preference_pair` responses but doesn't enforce the
contrastive contract from `sub-skills/dpo-pair-generator.md`. Today a DPO pair
with an empty rejected, a refusal-style rejected, or a 10× length blowout
between chosen/rejected can pass structural checks. Coverage doesn't report
DPO-specific metrics.

### Files to edit

- `scripts/verify.py` — add `dpo_errors(record, plan)` and call it from
  `heuristic_errors` for `response.format == "preference_pair"`.
- `scripts/coverage.py` — add a `compute_dpo_coverage(records, plan)` and
  surface results in the existing report under a `"dpo"` key.
- `scripts/utils/coverage_plan.py` — no change unless adding helpers.
- `sub-skills/dpo-pair-generator.md` — add a short paragraph linking to the
  new deterministic checks.
- `tests/test_pipeline.py` — add `DpoVerifyTests` and `DpoCoverageTests`.

### Behavior

In `verify.heuristic_errors`, when `response.format == "preference_pair"`:

- Extract `chosen = response.chosen`, `rejected = response.rejected`.
- Read `plan.dpo` (default `{}`):
  - `min_chosen_length` (default `args.min_response_length`)
  - `min_rejected_length` (default `args.min_response_length`)
  - `max_length_ratio` (default `8.0`) — `max(len_c,len_r) / max(1,min(len_c,len_r))`
  - `require_dpo_delta` (default `False`)
  - `forbid_refusal_in_rejected` (default `True`)
- Errors to emit:
  - `"DPO chosen response is too short"` if below min.
  - `"DPO rejected response is empty or too short"` if below min or whitespace.
  - `"DPO rejected response uses a refusal pattern"` if `REFUSAL_PATTERNS`
    match and `forbid_refusal_in_rejected` is set.
  - `"DPO chosen/rejected length ratio exceeds max_length_ratio"`.
  - `"DPO record is missing metadata.dpo_delta"` if required.
  - `"DPO chosen and rejected are identical"` if normalized text matches.

In `coverage.compute_dpo_coverage`, only consider `preference_pair` records
and report:

- `pair_count`
- `mean_chosen_length`, `mean_rejected_length`
- `length_ratio_p95`
- `dpo_delta_counts` (Counter over `metadata.dpo_delta`)
- `findings` list, populated when:
  - Plan sets `dpo.min_pair_count` and the corpus is below it.
  - Mean length ratio > plan-defined `dpo.max_mean_length_ratio` (default 3.0).
  - A single `dpo_delta` value owns > 60% of pairs and `dpo.max_share_per_delta`
    is set in the plan.

### Plan keys (document in `sub-skills/dpo-pair-generator.md`)

```json
{
  "dpo": {
    "min_chosen_length": 30,
    "min_rejected_length": 30,
    "max_length_ratio": 8.0,
    "require_dpo_delta": true,
    "forbid_refusal_in_rejected": true,
    "min_pair_count": 500,
    "max_mean_length_ratio": 3.0,
    "max_share_per_delta": 0.6,
    "blocking": true
  }
}
```

`section_is_blocking(plan, "dpo")` should gate failures the same way the
existing `provenance` and `research` sections do.

### Tests (`DpoVerifyTests`, `DpoCoverageTests`)

- Empty rejected ⇒ error.
- Refusal-style rejected ⇒ error when `forbid_refusal_in_rejected: true`,
  but no error when `false`.
- Length ratio violation ⇒ error.
- Missing `metadata.dpo_delta` ⇒ error when `require_dpo_delta: true`.
- Identical chosen/rejected ⇒ error.
- A clean DPO record with `dpo_delta`, balanced lengths ⇒ no errors.
- Coverage metrics produce a finding when `min_pair_count` not met.
- Coverage metrics emit `dpo_delta_counts` correctly.

---

## Task 3 — Web-fetch safety hardening (Issue #14, partial)

**Why.** `is_url_fetchable` already blocks scheme/private hosts, but
`fetch_url` itself has no max-bytes cap, no content-type allowlist, and no
per-domain rate limit. A 200 MB CDN page or a non-text response will currently
flow through `extract_text` and waste evidence-chunking budget.

### Files to edit

- `scripts/utils/web.py` — extend `fetch_url`, add `RateLimiter`.
- `scripts/research.py` — pass new options through; record fetch errors with
  reason in `sources.jsonl`.
- `tests/test_pipeline.py` — add `FetchSafetyTests`.

### Behavior

Extend `fetch_url` signature:

```python
def fetch_url(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_bytes: int = 2_000_000,
    allowed_content_types: tuple[str, ...] = ("text/html", "application/xhtml+xml", "text/plain"),
) -> WebPage:
```

- When using `requests`, stream the response and abort once
  `len(content) > max_bytes`. Set `WebPage.error = "max_bytes exceeded"` and
  return early with whatever was buffered (or empty content).
- After receiving headers, check `content-type` against
  `allowed_content_types`. If it doesn't match, return immediately with
  `error = "disallowed content-type: <observed>"`.
- For the `urllib` fallback, do the same with `read(max_bytes + 1)` and a
  size check.
- Never raise on these — populate `WebPage.error` so the caller can record it.

Add a small `RateLimiter`:

```python
class RateLimiter:
    def __init__(self, per_domain_seconds: float = 1.0) -> None: ...
    def wait(self, url: str) -> None:
        # blocks until the per-host minimum gap has elapsed
```

Use it in `scripts.research.run_native_backend` instead of the global
`time.sleep(args.rate_limit)`. Apply per `domain_from_url(source["url"])`.

### CLI flags on `scripts/research.py`

Add (with sensible defaults):

- `--max-bytes` (default `2_000_000`)
- `--allowed-content-types` (nargs+, default the tuple above)
- `--per-domain-rate-limit` (default `args.rate_limit`)

Forward these into `fetch_url` / `RateLimiter`.

### Tests (`FetchSafetyTests`)

Mock `requests.get` to return a fake response with a controlled
`iter_content`:

1. A 5 MB response with `max_bytes=1_000_000` produces
   `error == "max_bytes exceeded"` and `len(html_content) <= 1_000_000`.
2. A response with `content-type: application/pdf` produces
   `error == "disallowed content-type: application/pdf"` and empty content.
3. `RateLimiter(per_domain_seconds=0.05)` enforces ≥ 0.05 s between two
   `wait()` calls for the same host but does not block different hosts.

---

## Task 4 — Real MinHash + AST-normalized code dedup (Issue #10, partial)

**Why.** `--strategy minhash` accepts the flag but routes to the same
shingle-Jaccard path. The CLI promises a stronger near-duplicate detector and
should deliver one. Code dedup also benefits from AST-normalization for
Python responses so that variable-rename paraphrases collapse.

### Files to edit

- `scripts/utils/similarity.py` — add real MinHash, add code normalization.
- `scripts/dedup.py` — pass through new normalization flags.
- `tests/test_pipeline.py` — extend `DeduplicationTests` with new cases.

### Behavior

#### Real MinHash

Implement deterministic MinHash without external deps:

```python
def minhash_signature(tokens: set[str], *, num_perm: int = 64, seed: int = 0xC0DE) -> tuple[int, ...]: ...
def minhash_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float: ...
```

- Use `hashlib.blake2b` with a per-permutation seed derived from `(seed, i)`
  to avoid third-party dependencies.
- For the `minhash` strategy in `_near_score`:
  - Build the signature once per record and cache it on
    `SimilarityIndex.minhash_by_id`.
  - Compare via `minhash_similarity`.
- Document in the docstring that this is a MinHash *estimator* of Jaccard
  similarity, with `num_perm=64` giving roughly ±0.06 error at 0.85 threshold.

#### Code-aware normalization

Add:

```python
def normalize_code_text(text: str) -> str: ...
```

Heuristics:

- Detect Python ``` ```python ``` blocks (reuse existing regex).
- For each, attempt `ast.parse`; on success, walk the tree replacing
  `ast.Name.id` with `var_<N>` (in source order) and stripping comments via
  `ast.unparse`. Collapse whitespace.
- Rejoin normalized code with the surrounding prose.
- On `SyntaxError`, return the original text untouched.

### `scripts/dedup.py`

Add `--code-aware` flag (default `False`). When set, wrap `text_fn` with
`normalize_code_text` before feeding it to `find_duplicates`.

### Tests (extend `DeduplicationTests`)

1. Two Python responses that differ only by variable names
   (`def f(a):` vs `def f(b):`) collapse to a duplicate when `--code-aware`
   is on; stay distinct when off.
2. MinHash strategy: two records with token Jaccard ≈ 0.9 are flagged as
   duplicates with `threshold=0.8`; two records at Jaccard ≈ 0.4 are not.
3. MinHash signatures are deterministic — same input produces the same
   signature on every call.
4. The existing shingle/tfidf tests continue to pass unchanged.

---

## Task 5 — Extended LLM review schema (Issue #9, partial)

**Why.** Phase 3 added `structural_pass`, `instruction_following_pass`,
`grounding_pass`, and `format_pass`. The original plan also called for
`capability_delta_score` and `safety_notes`, plus a plan-level
`review_requirements` block with `min_capability_delta_score` and
`require_grounding_pass`. These are not in `verify.py.apply_review` today.

### Files to edit

- `scripts/verify.py` — extend `apply_review` to read
  `capability_delta_score` (int), `safety_notes` (string), and to honor
  `plan.review_requirements`.
- `sub-skills/llm-judge.md` — document the new fields in the review-file
  schema and the new plan keys.
- `tests/test_pipeline.py` — extend `VerifyEvidenceAndCollectedTests` (or
  add `ReviewSchemaTests`).

### Behavior

`apply_review(record, review)` should:

1. Persist `capability_delta_score` and `safety_notes` onto the record
   (`record["judge_capability_delta"]`, `record["judge_safety_notes"]`).
2. Read `plan.review_requirements`:
   - `min_capability_delta_score` (int, optional). If set and the review's
     `capability_delta_score` is below it, return `("verified_fail", "fail",
     score, reason="capability_delta_score below threshold")`.
   - `require_grounding_pass` (bool, default `False`). When true and the
     review omits `grounding_pass` or sets it false, fail.
   - `blocking` follows the existing `section_is_blocking` convention.
3. Backward compat: reviews lacking the new fields continue to work as
   before.

### Plan keys (document in `llm-judge.md`)

```json
{
  "review_requirements": {
    "min_capability_delta_score": 4,
    "require_grounding_pass": true,
    "blocking": true
  }
}
```

### Tests

- A review with `capability_delta_score: 2` and plan
  `min_capability_delta_score: 4` produces a `verified_fail`.
- A review with `capability_delta_score: 5` and the same plan passes.
- A review missing `grounding_pass` while `require_grounding_pass: true`
  fails.
- Old reviews with only `status/score/reason` still work.

---

## Task 6 — Per-domain cap during research collection (Issue #2, partial)

**Why.** Phase 1 sorts sources by `source_quality_score` after fetch, but it
does not cap how many sources a single domain can contribute. A dominant
domain (e.g., one Stack Overflow tag page that produces dozens of hits) can
still flood the evidence pool. The `coverage.py` `max_share_per_domain` check
is post-hoc — it surfaces the problem after generation, but doesn't prevent
it during collection.

### Files to edit

- `scripts/research.py` — apply a per-domain cap before evidence generation.
- `tests/test_pipeline.py` — extend `ResearchPipelineTests`.

### Behavior

Add to `parse_args`:

- `--max-sources-per-domain` (int, default `5`).

In `run_native_backend`, after URL dedup but before `fetch_source_text`, group
sources by `domain_from_url(source["url"])` and trim each group to the cap,
keeping the top-ranked items. Apply the cap again after scoring (a new domain
may become apparent only after `extract_text`).

Record the cap in the `coverage_report.json` summary so a user can see why a
source was skipped:

```json
{
  "per_domain_cap": 5,
  "domains_capped": {"stackoverflow.com": 12}
}
```

`domains_capped` lists domains where excess sources were dropped, with the
original count.

### Tests

- 8 sources from `example.com` and 2 from `other.org` with
  `--max-sources-per-domain 3` collapses to 5 sources total
  (3 + 2) with `domains_capped["example.com"] == 8`.
- Default cap of 5 is applied when the flag is omitted.
- Cap of 0 disables the cap (keep all sources).

---

## Task 7 — Split-leakage hardening (Issue #13)

**Why.** `get_cluster_key` in `scripts/export.py` falls back to a 6-word
instruction hash when scenario/topic/intent/subtopic/fingerprint metadata are
all missing. Two records with similar phrasings then collide into the same
cluster only if the first six words match, which is fragile. Issue #13 also
called for using evidence IDs and source URIs as cluster keys, plus a
`metadata.scenario_fingerprint` from research/seed generation, plus an audit
warning when too many records rely on the fallback.

### Files to edit

- `scripts/export.py` — extend `get_cluster_key` priority order.
- `scripts/research.py` — emit `metadata.scenario_fingerprint` on evidence
  rows so downstream record drafting can carry it forward.
- `sub-skills/seed-generator.md` — instruct the agent to copy
  `metadata.scenario_fingerprint` from evidence onto drafted records.
- `scripts/audit.py` — add a finding when fallback cluster keys exceed a
  share threshold.
- `tests/test_pipeline.py` — extend `AuditScriptTests` and add
  `ClusterKeyTests`.

### Behavior

`get_cluster_key(record)` priority (first non-empty wins):

1. `metadata.scenario_fingerprint` (new, preferred).
2. `metadata.scenario`.
3. `metadata.topic`, `metadata.intent`, `metadata.subtopic`,
   `metadata.fingerprint` (existing).
4. First evidence id from `metadata.evidence_ids` (so two records grounded
   in the same chunk land in the same split).
5. Hash of `metadata.source_uri` (so two records pulled from the same page
   land together).
6. The current 6-word instruction fallback. When this branch is taken, prefix
   the returned key with `fallback:` so downstream code can count fallback
   usage.

`research.py.evidence_from_source` should compute a stable
`scenario_fingerprint` per evidence row:

```python
metadata["scenario_fingerprint"] = stable_id(
    "scn",
    {"source_id": source["source_id"], "research_subquery_id": ...},
)
```

`audit.py` adds a new check: if `> 25%` of records produce a `fallback:`
cluster key, emit a Medium finding `"Cluster fallback overuse"` with the
percentage and a recommendation to add scenario/topic metadata.

### Tests

- `get_cluster_key` returns `metadata.scenario_fingerprint` when present.
- Falls back to `metadata.evidence_ids[0]` when fingerprint missing.
- Falls back to `source_uri` hash when evidence_ids missing.
- Fallback returns `fallback:<words>` when all metadata missing.
- `audit.py`: corpus where 40% of records use fallback keys produces the
  new finding.

---

## Task 8 — Wire Tasks 2–7 into `build_loop.py` and docs

After Tasks 2–7 are merged:

- `scripts/build_loop.py` — when a plan blocks on `dpo`, `review_requirements`,
  or fails research coverage, surface that in the final summary (mirror the
  existing `research_findings` integration around line 346).
- `docs/workflows.md` — document the new flags
  (`--strategy minhash`, `--code-aware`, `--max-bytes`,
  `--per-domain-rate-limit`, `--max-sources-per-domain`,
  `--allowed-content-types`).
- `SKILL.md` — add one-line bullets to the Research/evidence route showing
  the strict DPO plan, the extended review schema, and the
  `scenario_fingerprint` cluster key.
- Run `python3 -m pytest tests/ -x -q` and confirm green.

---

## Suggested commit cadence

1. `Phase 6: add tests for research, grounding, audit, and evidence pipeline`
2. `Phase 7: add deterministic DPO verification and coverage checks`
3. `Phase 8: harden web fetching with byte caps, content-type allowlist, per-domain rate limit`
4. `Phase 9: add real MinHash and AST-normalized code dedup`
5. `Phase 10: extend LLM review schema with capability_delta_score and review_requirements`
6. `Phase 11: enforce per-domain caps during research collection`
7. `Phase 12: add scenario_fingerprint and stronger split-leakage cluster keys`
8. `Phase 13: wire new gates into build_loop and update docs`

Keep each commit self-contained and green. If a task spawns surprises, raise
them in the commit body rather than expanding scope mid-commit.
