"""
Local collector — fetch content from web searches, URLs, or local files and
emit canonical JSONL records ready for agent-driven dataset creation.

This script is deterministic: it fetches and chunks content but does NOT
generate training examples. The host IDE agent reads the output JSONL and
drafts instruction/response pairs before importing into generate.py.

Usage:
  # Web search (IDE tools preferred — see sub-skills/local-collector.md)
  python3 scripts/collect.py --query "linux file permissions" --max-results 10

  # Explicit URLs
  python3 scripts/collect.py --urls https://example.com/article1 https://example.com/article2

  # URLs from file
  python3 scripts/collect.py --url-file urls.txt

  # Local files or directories
  python3 scripts/collect.py --paths ./docs ./README.md --extensions md txt

  # Combined
  python3 scripts/collect.py --query "bash scripting" --urls https://example.com --paths ./scripts/

  # Then feed into the pipeline
  python3 scripts/generate.py --input workspace/collected_<timestamp>.jsonl \\
      --source-type url_reference --tool-context codex
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import build_record_id
from scripts.utils.files import write_json, write_jsonl
from scripts.utils.web import (
    LocalFile,
    chunk_text,
    extract_text,
    fetch_url,
    read_local_file,
    search_web,
    walk_repo,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT_DIR / "workspace"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect content from web searches, URLs, or local files and emit "
            "canonical JSONL records for agent-driven dataset creation. "
            "This script does not call external LLM APIs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    src = parser.add_argument_group("source modes (combinable)")
    src.add_argument(
        "--query",
        metavar="QUERY",
        help=(
            "Web search query. Tries SerpAPI/Bing/Google CSE API keys from env vars, "
            "then duckduckgo-search lib, then DuckDuckGo HTML scraping (stdlib fallback)."
        ),
    )
    src.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Explicit URLs to fetch and extract content from.",
    )
    src.add_argument(
        "--url-file",
        metavar="PATH",
        help="Text file containing one URL per line.",
    )
    src.add_argument(
        "--paths",
        nargs="+",
        metavar="PATH",
        help="Local file or directory paths to collect from.",
    )

    search = parser.add_argument_group("search options")
    search.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum search results to fetch per query (default: 10).",
    )
    fetch_group = search.add_mutually_exclusive_group()
    fetch_group.add_argument(
        "--fetch-content",
        dest="fetch_content",
        action="store_true",
        default=True,
        help="Fetch and extract full page content for search results (default).",
    )
    fetch_group.add_argument(
        "--snippets-only",
        dest="fetch_content",
        action="store_false",
        help="Only collect search result snippets; do not fetch full pages.",
    )

    content = parser.add_argument_group("content options")
    content.add_argument(
        "--extensions",
        nargs="+",
        metavar="EXT",
        help="File extensions to include when walking directories (e.g. md py txt).",
    )
    content.add_argument(
        "--max-files",
        type=int,
        default=200,
        help="Maximum files to collect when walking directories (default: 200).",
    )
    content.add_argument(
        "--max-chunk-chars",
        type=int,
        default=3000,
        help="Maximum characters per output chunk/record (default: 3000).",
    )
    content.add_argument(
        "--overlap-chars",
        type=int,
        default=200,
        help="Overlap characters between consecutive chunks (default: 200).",
    )
    content.add_argument(
        "--fetch-timeout",
        type=int,
        default=15,
        help="HTTP fetch timeout in seconds (default: 15).",
    )
    content.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Seconds to wait between HTTP requests (default: 1.0).",
    )

    out = parser.add_argument_group("output options")
    out.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "Output JSONL path. Defaults to workspace/collected_<timestamp>.jsonl."
        ),
    )
    out.add_argument(
        "--task-type",
        choices=("sft", "dpo"),
        default="sft",
        help="Task type for collected records (default: sft).",
    )
    out.add_argument(
        "--tool-context",
        default="generic",
        help="Originating tool context (codex, claude, antigravity, or generic).",
    )
    out.add_argument(
        "--report",
        metavar="PATH",
        help="Optional path to write a JSON summary report.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_record(
    *,
    chunk: str,
    source_uri: str,
    title: str,
    chunk_index: int,
    source_type: str,
    task_type: str,
    collection_query: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical pipeline record from a collected text chunk."""
    metadata: dict[str, Any] = {
        "difficulty": "unspecified",
        "persona": "general",
        "source_type": source_type,
        "source_title": title,
        "chunk_index": chunk_index,
        "collected_at": _utc_now(),
        "tags": [],
    }
    if collection_query:
        metadata["collection_query"] = collection_query
    if extra_metadata:
        metadata.update(extra_metadata)

    if collection_query:
        instruction = (
            f"Review the following source material and extract training examples "
            f"relevant to: {collection_query}."
        )
    else:
        instruction = (
            "Review the following source material and extract training examples from it."
        )

    record: dict[str, Any] = {
        "task_type": task_type,
        "instruction": instruction,
        "context": title,
        "response": {"format": "single", "text": chunk},
        "metadata": metadata,
        "pipeline_status": "pending",
        "status": "collected",
        "source_type": source_type,
        "source_uri": source_uri,
    }
    record["id"] = build_record_id({
        "instruction": instruction,
        "source_uri": source_uri,
        "chunk_index": chunk_index,
    })
    return record


# ---------------------------------------------------------------------------
# Collection modes
# ---------------------------------------------------------------------------

def collect_from_query(
    query: str,
    *,
    max_results: int = 10,
    fetch_content: bool = True,
    max_chunk_chars: int = 3000,
    overlap_chars: int = 200,
    fetch_timeout: int = 15,
    rate_limit: float = 1.0,
    task_type: str = "sft",
) -> list[dict[str, Any]]:
    """Search the web and collect content as canonical records.

    Note: In the agentic workflow the IDE's native search tools are tried first
    (see sub-skills/local-collector.md). This function is called when the script
    runs directly or as a fallback.
    """
    print(f"[collect] Web search: {query!r} (max_results={max_results})", file=sys.stderr, flush=True)
    results = search_web(query, max_results=max_results, rate_limit_seconds=rate_limit)

    if not results:
        print("[collect] Warning: web search returned no results.", file=sys.stderr, flush=True)
        return []

    print(f"[collect] Found {len(results)} results.", file=sys.stderr, flush=True)
    records: list[dict[str, Any]] = []

    for result in results:
        if not result.url:
            continue

        if fetch_content:
            print(f"[collect] Fetching: {result.url}", file=sys.stderr, flush=True)
            page = fetch_url(result.url, timeout=fetch_timeout)
            if page.error or not page.html_content:
                print(
                    f"[collect] Warning: fetch failed for {result.url}: {page.error}",
                    flush=True,
                )
                # Fall back to snippet if available
                if result.snippet:
                    records.append(_make_record(
                        chunk=result.snippet,
                        source_uri=result.url,
                        title=result.title,
                        chunk_index=0,
                        source_type="internet_research",
                        task_type=task_type,
                        collection_query=query,
                    ))
                continue

            extracted = extract_text(page.html_content, result.url)
            text = extracted.text or result.snippet
            title = extracted.title or result.title
            time.sleep(rate_limit)
        else:
            text = result.snippet
            title = result.title

        if not text.strip():
            continue

        for i, chunk in enumerate(
            chunk_text(text, max_chars=max_chunk_chars, overlap=overlap_chars)
        ):
            records.append(_make_record(
                chunk=chunk,
                source_uri=result.url,
                title=title,
                chunk_index=i,
                source_type="internet_research",
                task_type=task_type,
                collection_query=query,
            ))

    return records


def collect_from_urls(
    urls: list[str],
    *,
    max_chunk_chars: int = 3000,
    overlap_chars: int = 200,
    fetch_timeout: int = 15,
    rate_limit: float = 1.0,
    task_type: str = "sft",
) -> list[dict[str, Any]]:
    """Fetch explicit URLs and collect content as canonical records."""
    records: list[dict[str, Any]] = []

    for url in urls:
        url = url.strip()
        if not url:
            continue

        print(f"[collect] Fetching: {url}", file=sys.stderr, flush=True)
        page = fetch_url(url, timeout=fetch_timeout)

        if page.error or not page.html_content:
            print(f"[collect] Warning: fetch failed for {url}: {page.error}", file=sys.stderr, flush=True)
            continue

        extracted = extract_text(page.html_content, url)
        if not extracted.text.strip():
            print(f"[collect] Warning: no text extracted from {url}", file=sys.stderr, flush=True)
            continue

        for i, chunk in enumerate(
            chunk_text(extracted.text, max_chars=max_chunk_chars, overlap=overlap_chars)
        ):
            records.append(_make_record(
                chunk=chunk,
                source_uri=url,
                title=extracted.title,
                chunk_index=i,
                source_type="url_reference",
                task_type=task_type,
            ))

        time.sleep(rate_limit)

    return records


def collect_from_paths(
    paths: list[str],
    *,
    extensions: set[str] | None = None,
    max_files: int = 200,
    max_chunk_chars: int = 3000,
    overlap_chars: int = 200,
    task_type: str = "sft",
) -> list[dict[str, Any]]:
    """Collect content from local files and directories."""
    records: list[dict[str, Any]] = []

    for raw_path in paths:
        p = Path(raw_path)
        if not p.exists():
            print(f"[collect] Warning: path does not exist: {p}", file=sys.stderr, flush=True)
            continue

        if p.is_file():
            local_files: list[LocalFile] = []
            try:
                content = read_local_file(p)
                local_files = [LocalFile(
                    path=str(p), content=content, extension=p.suffix.lower()
                )]
            except Exception as exc:
                print(f"[collect] Warning: could not read {p}: {exc}", file=sys.stderr, flush=True)
                continue
        else:
            ext_set = {f".{e.lstrip('.')}" for e in extensions} if extensions else None
            print(f"[collect] Walking: {p}", file=sys.stderr, flush=True)
            local_files = walk_repo(p, extensions=ext_set, max_files=max_files)

        print(f"[collect] Collected {len(local_files)} file(s) from {raw_path}", file=sys.stderr, flush=True)

        for lf in local_files:
            if not lf.content.strip():
                continue
            file_name = Path(lf.path).name
            for i, chunk in enumerate(
                chunk_text(lf.content, max_chars=max_chunk_chars, overlap=overlap_chars)
            ):
                records.append(_make_record(
                    chunk=chunk,
                    source_uri=lf.path,
                    title=file_name,
                    chunk_index=i,
                    source_type="url_reference",
                    task_type=task_type,
                    extra_metadata={
                        "source_path": lf.path,
                        "file_extension": lf.extension,
                    },
                ))

    return records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    if not any([args.query, args.urls, args.url_file, args.paths]):
        raise SystemExit(
            "Provide at least one source mode: --query, --urls, --url-file, or --paths."
        )

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output) if args.output
        else WORKSPACE_DIR / f"collected_{timestamp}.jsonl"
    )

    all_records: list[dict[str, Any]] = []

    # --- Web search ---
    if args.query:
        all_records.extend(collect_from_query(
            args.query,
            max_results=args.max_results,
            fetch_content=args.fetch_content,
            max_chunk_chars=args.max_chunk_chars,
            overlap_chars=args.overlap_chars,
            fetch_timeout=args.fetch_timeout,
            rate_limit=args.rate_limit,
            task_type=args.task_type,
        ))

    # --- URL list ---
    urls: list[str] = list(args.urls or [])
    if args.url_file:
        url_file = Path(args.url_file)
        if url_file.exists():
            urls.extend(url_file.read_text(encoding="utf-8").splitlines())
        else:
            print(f"[collect] Warning: --url-file not found: {args.url_file}", file=sys.stderr, flush=True)

    if urls:
        all_records.extend(collect_from_urls(
            [u for u in urls if u.strip()],
            max_chunk_chars=args.max_chunk_chars,
            overlap_chars=args.overlap_chars,
            fetch_timeout=args.fetch_timeout,
            rate_limit=args.rate_limit,
            task_type=args.task_type,
        ))

    # --- Local files / repos ---
    if args.paths:
        ext_set = set(args.extensions) if args.extensions else None
        all_records.extend(collect_from_paths(
            args.paths,
            extensions=ext_set,
            max_files=args.max_files,
            max_chunk_chars=args.max_chunk_chars,
            overlap_chars=args.overlap_chars,
            task_type=args.task_type,
        ))

    # Deduplicate by record id
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for rec in all_records:
        if rec["id"] not in seen:
            seen.add(rec["id"])
            unique.append(rec)

    write_jsonl(output_path, unique)
    print(f"[collect] Wrote {len(unique)} records → {output_path}", file=sys.stderr, flush=True)

    summary: dict[str, Any] = {
        "output": str(output_path),
        "records_collected": len(unique),
        "tool_context": args.tool_context,
        "sources": {
            "query": args.query,
            "url_count": len([u for u in urls if u.strip()]),
            "path_count": len(args.paths or []),
        },
        "next_step": (
            "Convert collected raw chunks into canonical draft records before import. "
            "For deeper sourcing, run scripts/research.py to create evidence.jsonl, "
            "then draft records with metadata.evidence_ids/reference_urls."
        ),
        "warning": (
            "Records with status=collected are raw source material. "
            "They must not be verified/exported as training examples directly."
        ),
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
