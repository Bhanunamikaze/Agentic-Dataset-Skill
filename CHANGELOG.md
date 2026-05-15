# Changelog

All notable changes to this project should be documented here.

## [Unreleased]

### Added

- Canonical dataset pipeline supporting both SFT and DPO workflows end-to-end (generate → augment → verify → dedup → audit → export).
- 13 cognitive sub-skills covering dataset strategy, seed generation, diversity, DPO pair construction, quality filtering, LLM judging, deduplication, formatting, data cards, verification, auditing, grounding, and research planning.
- 14 deterministic pipeline scripts in `scripts/` (`generate.py`, `build_loop.py`, `coverage.py`, `augment.py`, `verify.py`, `dedup.py`, `export.py`, `collect.py`, `research.py`, `grounding.py`, `audit.py`, `quality_report.py`, `review_batch.py`, `browser_collect.py`).
- SQLite-backed resumable state via `scripts/utils/db.py` for long-running build loops.
- Native research and evidence pipeline that feeds verification, coverage, and grounding scoring.
- `--dedup-on` flag so dedup can be scoped to `instruction`, `prompt`, or full-record signatures.

### Changed

- Grounding score threshold raised to 0.20 to suppress weakly-supported records during verification.
- Dedup strategies hardened with stopword filtering and configurable signature surface (`scripts/utils/source_dedup.py`, `similarity.py`).
- Build verification now consumes research evidence and coverage metrics together rather than as independent checks.

### Fixed

- Refusal-detection regex anchoring tightened so short fragments like "I cannot" no longer match inside legitimate content.
- Anti-trope detector now catches templated assistant phrases that previously slipped through.
- DPO records now have chosen-side checks for refusals, anti-tropes, and grounding so the preferred response cannot regress against the rejected response.
- Context leakage audit added so model-visible fields never expose hidden plan or system text.
