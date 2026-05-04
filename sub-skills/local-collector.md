# local-collector

Use this when the user wants to build a dataset from web searches, specific URLs, or local files and repositories.

## When to Use This Sub-skill

Route here when the request mentions:

- "search the web for ..."
- "use these URLs / links / posts"
- "scrape / read this website"
- "use this repo / codebase / docs as source material"
- "build a dataset from online resources"

## Step 1 — Try IDE Native Search First

Before invoking `scripts/collect.py`, try the IDE's own search and browsing tools:

1. Use the IDE's built-in `search_web` or browser tool to search for the topic.
2. Use the IDE's `read_url_content` or browsing tool to fetch and read pages.
3. If the IDE tools return usable results, write canonical draft records directly from the extracted text and import them with `generate.py`.

Only proceed to Step 2 if:
- The IDE's search tools are unavailable or rate-limited.
- The collection is large (10+ URLs or a directory walk).
- The user explicitly requests the local script.

## Step 2 — Use the Local Collector Script

When IDE tools are insufficient, invoke `scripts/collect.py` directly.

### Web search collection

```bash
python3 scripts/collect.py \
  --query "your topic here" \
  --max-results 10 \
  --tool-context codex
```

The script tries search backends in order:
1. SerpAPI (`SERPAPI_KEY` env var)
2. Bing Search API (`BING_API_KEY` env var)
3. Google Custom Search (`GOOGLE_API_KEY` + `GOOGLE_CSE_ID` env vars)
4. `duckduckgo-search` library (if installed)
5. DuckDuckGo HTML scraping (stdlib, always available)

### URL list collection

```bash
# Inline URLs
python3 scripts/collect.py \
  --urls https://example.com/article1 https://example.com/article2 \
  --tool-context codex

# URLs from a file (one per line)
python3 scripts/collect.py \
  --url-file urls.txt \
  --tool-context codex
```

### Local files and repository collection

```bash
python3 scripts/collect.py \
  --paths ./docs ./README.md \
  --extensions md txt rst \
  --tool-context codex
```

### Combined (all modes together)

```bash
python3 scripts/collect.py \
  --query "bash scripting best practices" \
  --urls https://example.com/bash-guide \
  --paths ./scripts/ \
  --max-results 10 \
  --max-chunk-chars 2000 \
  --tool-context codex
```

## Step 3 — Review and Draft Training Records

The collector outputs `workspace/collected_<timestamp>.jsonl` containing raw text chunks. Each record has:

- `status: collected` — raw material, not yet a training example
- `context`: the page/file title
- `response.text`: the extracted text chunk
- `metadata.source_url` or `metadata.source_path`: provenance
- `metadata.collection_query`: the search query used (if web search mode)

**Do not pass collected records directly into `verify.py`.** Instead:

1. Read the collected JSONL using the IDE's file-reading tools.
2. For each chunk (or group of related chunks), draft a proper canonical record with a specific `instruction` and a well-structured `response` tailored to the dataset goal.
3. Save the drafted records to a new JSONL file (e.g., `workspace/drafts.jsonl`).
4. Import the drafts into the pipeline:

```bash
python3 scripts/generate.py \
  --input workspace/drafts.jsonl \
  --source-type url_reference \
  --tool-context codex
```

Then continue with the standard verify → dedup → export pipeline.

## Quality Guidelines

- Prefer specific, concrete chunks over generic summaries.
- Discard chunks that are navigation text, cookie banners, or boilerplate.
- If a chunk requires significant inference to form a useful example, that is appropriate agent reasoning.
- Use `--max-chunk-chars 2000` for dense technical content, `3000` (default) for general prose.
- Use `--snippets-only` to skip full-page fetches when snippet coverage is sufficient.

## Rate Limiting

The script defaults to a 1-second delay between HTTP requests (`--rate-limit 1.0`). Increase this for polite crawling of small sites.

## Raw collection guard

`collect.py` output is source material only. Records with `status: collected` are not training examples and must not be sent directly through verification/export. Convert them into canonical draft records first, or use `scripts/research.py` to create `evidence.jsonl` and draft records with `metadata.evidence_ids`.
