# Structured Ingestion Plan

## Objective

Build a new structured ingestion path that takes a directory of repos, code files, and articles and turns them into dataset drafts automatically.

This path must:

- stay separate from the existing raw chunk collector
- preserve provenance and file relationships
- parse C and C++ repositories first
- keep related source and header files together
- understand Visual Studio project structure without requiring a build
- extract code snippets from `html`, `htm`, and `mhtml` with surrounding context
- prepare bounded source bundles for LLM drafting so context is preserved without overloading prompts

## Confirmed Decisions

- Default flow: `directory -> parsed artifacts -> dataset drafts` automatically
- Optional parser dependencies are allowed
- V1 source scope: `c`, `cc`, `cpp`, `cxx`, `h`, `hh`, `hpp`, `hxx`, `inl`, `asm`, `s`, `inc`, `asmx`, `html`, `htm`, `mhtml`, `md`, `txt`, and code/text files already handled by the repo
- Deferred for later: `pdf`, `docx`, binary document formats, and compilation/build execution

## Status Legend

- `completed`
- `in_progress`
- `pending`
- `blocked`

## Current Status Summary

- Branch setup: `completed`
- Planning document: `completed`
- Structured ingestion implementation: `completed`

## Proposed Architecture

Add a new structured ingestion path rather than extending `scripts/collect.py`.

Planned new components:

- `scripts/ingest.py`
  - top-level entry point for structured source ingestion
- `scripts/utils/discovery.py`
  - path walking, project detection, source classification, manifest creation
- `scripts/utils/artifacts.py`
  - artifact writing and loading helpers
- `scripts/utils/parsers/base.py`
  - parser interface and shared helpers
- `scripts/utils/parsers/c_family.py`
  - C/C++ parsing, include graph extraction, header/source pairing
- `scripts/utils/parsers/html.py`
  - `html` / `htm` / `mhtml` article parsing and snippet extraction
- `resources/internal-schema/source_artifact_schema.json`
  - schema for parsed source artifacts and relation records
- `workspace/ingest_runs/<run_id>/`
  - run-local parsed artifacts, manifests, bundles, and reports

## Planned Workspace Outputs

Each structured ingestion run should write:

- `manifest.json`
- `files.jsonl`
- `units.jsonl`
- `relations.jsonl`
- `bundles.jsonl`
- `ingest_report.json`

Definitions:

- `files.jsonl`: one record per source file with path, type, hash, project membership, and provenance
- `units.jsonl`: extracted symbols, snippets, sections, and chunkable semantic units
- `relations.jsonl`: links such as `includes`, `declares`, `implements`, `companion_of`, `belongs_to_project`, and `snippet_from`
- `bundles.jsonl`: bounded context packages used to draft dataset records

## Task List

| ID | Task | Deliverables | Status |
|---|---|---|---|
| SI-00 | Create branch and planning baseline | `coding-dataset` branch, `plan.md` | `completed` |
| SI-01 | Add structured ingestion entry point | `scripts/ingest.py`, CLI arguments, run directory creation, summary report | `completed` |
| SI-02 | Add source artifact schema and helpers | `resources/internal-schema/source_artifact_schema.json`, `scripts/utils/artifacts.py` | `completed` |
| SI-03 | Add discovery layer | `scripts/utils/discovery.py`, source classification, project detection, file manifests | `completed` |
| SI-04 | Add parser registry | `scripts/utils/parsers/base.py`, parser dispatch by file type | `completed` |
| SI-05 | Implement C/C++ parser core | symbol extraction, include extraction, companion file detection, fallback heuristic mode | `completed` |
| SI-06 | Add Visual Studio project awareness | `.sln`, `.vcxproj`, `.vcxproj.filters` parsing and project membership mapping | `completed` |
| SI-07 | Build C/C++ context bundler | bundle primary file with related headers, sources, project metadata, and include neighbors | `completed` |
| SI-08 | Implement HTML/HTM/MHTML parser | DOM cleanup, code block extraction, snippet context windows, provenance capture | `completed` |
| SI-09 | Add automatic draft generation from bundles | transform `bundles.jsonl` into canonical dataset drafts for downstream pipeline use | `completed` |
| SI-10 | Integrate with existing pipeline | import generated drafts through `generate.py`, preserve provenance metadata | `completed` |
| SI-11 | Add tests and fixtures | C repo fixture, C++ repo fixture, Visual Studio fixture, HTML/MHTML fixture, end-to-end tests | `completed` |
| SI-12 | Update docs and skill instructions | `README.md`, `docs/workflows.md`, `SKILL.md`, usage examples | `completed` |

## Execution Phases

### Phase 1: Ingestion Scaffold

Scope:

- create the structured ingestion CLI
- define artifact schemas and workspace layout
- add source discovery and parser dispatch

Tasks:

- `SI-01`
- `SI-02`
- `SI-03`
- `SI-04`

Status: `completed`

### Phase 2: C/C++ Repository Parsing

Scope:

- parse C and C++ files
- preserve source/header relationships
- understand Visual Studio project structure
- emit code bundles for downstream drafting

Tasks:

- `SI-05`
- `SI-06`
- `SI-07`

Status: `completed`

### Phase 3: HTML, HTM, and MHTML Parsing

Scope:

- extract article text and code snippets
- preserve nearby narrative context and section headings
- emit snippet-oriented bundles for drafting

Tasks:

- `SI-08`

Status: `completed`

### Phase 4: Dataset Draft Automation

Scope:

- convert parsed bundles directly into canonical dataset drafts
- keep the raw collector untouched
- integrate with the existing `generate -> verify -> dedup -> export` flow

Tasks:

- `SI-09`
- `SI-10`

Status: `completed`

### Phase 5: Reliability and Documentation

Scope:

- add fixtures, regression coverage, and end-to-end tests
- document the new workflow for skill users

Tasks:

- `SI-11`
- `SI-12`

Status: `completed`

## V1 Parsing Rules

### C/C++

- group source and header companions by basename and include graph
- capture `#include` relationships
- extract top-level symbols where possible
- record unresolved includes instead of silently discarding them
- prefer deterministic parsing first, then use the LLM only on bounded bundles

### Visual Studio

- parse project and solution membership from `.sln` and `.vcxproj` files
- use `.vcxproj.filters` to preserve logical structure when present
- do not require Windows, MSBuild, or compilation for V1

### HTML / HTM / MHTML

- strip non-content boilerplate where possible
- extract each code block as a separate unit
- capture section heading, surrounding paragraphs, source path, and inferred language
- treat `mhtml` as an article source with embedded page content when decodable

## Non-Goals for V1

- compiling or executing source projects
- PDF or DOCX parsing
- binary reverse-engineering
- full semantic cross-repo call graph construction
- language support beyond the approved C/C++ and article-focused first pass

## Commit Plan

Each implementation step should be committed separately with a detailed message describing:

- what changed
- which tasks moved status
- which files were added or modified
- what was tested

Initial commit for this document:

- adds `plan.md`
- records the approved structured ingestion architecture
- defines task IDs and statuses for the implementation sequence
