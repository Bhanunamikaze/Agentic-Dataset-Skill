"""
Research/evidence module for AI-Dataset-Generator.

This is the replacement for using a generic collector as the research layer.
It produces source and evidence artifacts that the host agent can use to draft
canonical training records with traceable provenance.

Default backend: native deterministic planner + search/fetch/chunk.
Optional backend: gpt_researcher, only when installed and explicitly requested.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.files import write_json, write_jsonl
from scripts.utils.research_plan import build_research_plan, load_json_object
from scripts.utils.source_dedup import dedupe_sources
from scripts.utils.source_quality import (
    classify_source_type,
    domain_from_url,
    source_distribution,
    source_quality_score,
)
from scripts.utils.web import (
    LocalFile,
    RateLimiter,
    chunk_text,
    extract_text,
    fetch_url,
    is_url_fetchable,
    read_local_file,
    search_web_all_backends,
    walk_repo,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT_DIR / "workspace"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan, collect, score, and chunk research evidence for dataset generation."
    )
    src = parser.add_argument_group("source modes")
    src.add_argument("--query", help="Dataset/research topic or user request.")
    src.add_argument("--urls", nargs="+", help="Explicit URLs to include as sources.")
    src.add_argument("--url-file", help="File containing URLs, one per line.")
    src.add_argument("--paths", nargs="+", help="Local files or directories to include as sources.")

    parser.add_argument("--backend", choices=("native", "gpt_researcher"), default="native")
    parser.add_argument("--plan-file", help="Coverage plan used to expand research subqueries.")
    parser.add_argument("--taxonomy-file", help="Optional taxonomy JSON object used to expand subqueries.")
    parser.add_argument("--max-subqueries", type=int, default=12)
    parser.add_argument("--max-results-per-query", type=int, default=8)
    parser.add_argument("--max-sources", type=int, default=40)
    parser.add_argument("--max-chunk-chars", type=int, default=2400)
    parser.add_argument("--overlap-chars", type=int, default=160)
    parser.add_argument("--fetch-timeout", type=int, default=15)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--snippets-only", action="store_true", help="Do not fetch full web pages.")
    parser.add_argument("--allow-private-network", action="store_true", help="Permit localhost/private IP fetches.")
    parser.add_argument("--extensions", nargs="+", help="Extensions for local directory walking.")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--tool-context", default="generic")
    parser.add_argument("--output-dir", help="Defaults to workspace/research_<timestamp>.")
    parser.add_argument("--report", help="Optional JSON summary report path.")
    parser.add_argument("--max-sources-per-domain", type=int, default=5, help="Maximum sources per domain during collection. 0 = no cap.")
    parser.add_argument("--max-bytes", type=int, default=2_000_000, help="Max response bytes per fetch.")
    parser.add_argument("--allowed-content-types", nargs="+", default=None, help="Allowed content-type prefixes. Default: html, xhtml, plain text.")
    parser.add_argument("--per-domain-rate-limit", type=float, default=None, help="Seconds between fetches to the same domain. Defaults to --rate-limit.")
    parser.add_argument(
        "--min-source-quality-score",
        type=float,
        default=0.0,
        help="Drop sources with quality score below this threshold before chunking evidence (0.0 = keep all).",
    )
    parser.add_argument(
        "--max-evidence-per-source",
        type=int,
        default=0,
        help="Cap evidence chunks per source (0 = unlimited).",
    )
    return parser.parse_args()


def load_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls or [])
    if args.url_file:
        path = Path(args.url_file)
        if path.exists():
            urls.extend(path.read_text(encoding="utf-8").splitlines())
    return [url.strip() for url in urls if url.strip()]


def build_web_sources(args: argparse.Namespace, research_plan: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for subquery in research_plan.get("subqueries", []):
        query = str(subquery.get("query") or "").strip()
        if not query:
            continue
        print(f"[research] Searching: {query}", file=sys.stderr, flush=True)
        results = search_web_all_backends(
            query,
            max_results=args.max_results_per_query,
            rate_limit_seconds=args.rate_limit,
        )
        for rank, result in enumerate(results, start=1):
            if not result.url:
                continue
            sources.append(
                {
                    "source_id": stable_id("src", {"url": result.url}),
                    "url": result.url,
                    "title": result.title,
                    "snippet": result.snippet,
                    "query": args.query,
                    "research_subquery": query,
                    "research_subquery_id": subquery.get("id"),
                    "rank": rank,
                    "source_mode": "web_search",
                    "retrieved_at": utc_now(),
                }
            )
    return sources


def build_explicit_url_sources(args: argparse.Namespace, urls: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": stable_id("src", {"url": url}),
            "url": url,
            "title": url,
            "snippet": "",
            "query": args.query,
            "research_subquery": args.query,
            "research_subquery_id": "explicit_url",
            "rank": index,
            "source_mode": "explicit_url",
            "retrieved_at": utc_now(),
        }
        for index, url in enumerate(urls, start=1)
    ]


def fetch_source_text(
    source: dict[str, Any],
    args: argparse.Namespace,
    rate_limiter: "RateLimiter | None" = None,
) -> tuple[str, str, str | None]:
    url = str(source.get("url") or "")
    if args.snippets_only:
        return str(source.get("title") or url), str(source.get("snippet") or ""), None
    if not is_url_fetchable(url, allow_private_network=args.allow_private_network):
        return str(source.get("title") or url), str(source.get("snippet") or ""), "url blocked by safety policy"
    allowed_ct = tuple(args.allowed_content_types) if getattr(args, "allowed_content_types", None) else ("text/html", "application/xhtml+xml", "text/plain")
    page = fetch_url(url, timeout=args.fetch_timeout, max_bytes=getattr(args, "max_bytes", 2_000_000), allowed_content_types=allowed_ct)
    if page.error and not page.html_content:
        return str(source.get("title") or url), str(source.get("snippet") or ""), page.error or "empty response"
    extracted = extract_text(page.html_content, url)
    text = extracted.text or str(source.get("snippet") or "")
    title = extracted.title or str(source.get("title") or url)
    if rate_limiter is not None:
        rate_limiter.wait(url)
    else:
        time.sleep(args.rate_limit)
    return title, text, page.error if page.error else None


def evidence_from_source(source: dict[str, Any], text: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, chunk in enumerate(
        chunk_text(text, max_chars=args.max_chunk_chars, overlap=args.overlap_chars)
    ):
        evidence_id = stable_id(
            "ev",
            {
                "source_id": source["source_id"],
                "chunk_index": index,
                "chunk": chunk[:240],
            },
        )
        metadata: dict[str, Any] = {
            "query": source.get("query"),
            "research_subquery": source.get("research_subquery"),
            "research_subquery_id": source.get("research_subquery_id"),
            "domain": source.get("domain"),
            "source_quality_score": source.get("source_quality_score"),
            "source_type_detail": source.get("source_type_detail"),
            "retrieved_at": source.get("retrieved_at"),
        }
        metadata["scenario_fingerprint"] = stable_id(
            "scn",
            {
                "source_id": source["source_id"],
                "research_subquery_id": source.get("research_subquery_id") or "unknown",
            },
        )
        evidence.append(
            {
                "evidence_id": evidence_id,
                "source_id": source["source_id"],
                "source_uri": source.get("url") or source.get("path"),
                "title": source.get("title") or "",
                "text": chunk,
                "chunk_index": index,
                "metadata": metadata,
            }
        )
    max_per = getattr(args, "max_evidence_per_source", 0)
    if max_per and len(evidence) > max_per:
        evidence = evidence[:max_per]
    return evidence


def collect_local_sources(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if not args.paths:
        return sources, evidence
    extensions = {f".{item.lstrip('.')}" for item in args.extensions} if args.extensions else None
    for raw_path in args.paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        local_files: list[LocalFile]
        if path.is_file():
            try:
                local_files = [LocalFile(path=str(path), content=read_local_file(path), extension=path.suffix)]
            except Exception:
                local_files = []
        else:
            local_files = walk_repo(path, extensions=extensions, max_files=args.max_files)
        for lf in local_files:
            source = {
                "source_id": stable_id("src", {"path": lf.path}),
                "path": lf.path,
                "url": "",
                "title": Path(lf.path).name,
                "snippet": lf.content[:500],
                "query": args.query,
                "research_subquery": args.query,
                "research_subquery_id": "local_file",
                "rank": 0,
                "source_mode": "local_file",
                "domain": "local",
                "source_type_detail": "local_document",
                "source_quality_score": source_quality_score(
                    title=Path(lf.path).name,
                    snippet=lf.content[:500],
                    text=lf.content,
                    query=args.query or "",
                ),
                "retrieved_at": utc_now(),
                "status": "fetched",
            }
            sources.append(source)
            evidence.extend(evidence_from_source(source, lf.content, args))
    return sources, evidence


def write_outputs(
    *,
    output_dir: Path,
    research_plan: dict[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    args: argparse.Namespace,
    domains_capped: dict[str, int] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "research_plan.json"
    sources_path = output_dir / "sources.jsonl"
    evidence_path = output_dir / "evidence.jsonl"
    coverage_path = output_dir / "coverage_report.json"

    distribution = source_distribution(sources)
    evidence_by_subquery = Counter(
        str(item.get("metadata", {}).get("research_subquery_id") or "unknown") for item in evidence
    )
    coverage_report = {
        "query": args.query,
        "backend": args.backend,
        "tool_context": args.tool_context,
        "sources_collected": len(sources),
        "evidence_chunks": len(evidence),
        "unique_domains": distribution["unique_domains"],
        "domain_counts": distribution["domain_counts"],
        "source_type_counts": distribution["source_type_counts"],
        "evidence_by_subquery": dict(sorted(evidence_by_subquery.items())),
        "generated_at": utc_now(),
        "per_domain_cap": getattr(args, "max_sources_per_domain", 5),
        "domains_capped": domains_capped or {},
        "sources_filtered_low_quality": sum(
            1 for s in sources if s.get("status") == "filtered_low_quality"
        ),
        "evidence_cap_active": bool(getattr(args, "max_evidence_per_source", 0) > 0),
    }

    write_json(plan_path, research_plan)
    write_jsonl(sources_path, sources)
    write_jsonl(evidence_path, evidence)
    write_json(coverage_path, coverage_report)
    return {
        "output_dir": str(output_dir),
        "research_plan": str(plan_path),
        "sources": str(sources_path),
        "evidence": str(evidence_path),
        "coverage_report": str(coverage_path),
        **coverage_report,
        "next_step": "Draft canonical records from evidence.jsonl. Put evidence IDs in metadata.evidence_ids and URLs in metadata.reference_urls/source_uri.",
    }


async def run_gpt_researcher_backend(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    if not args.query:
        raise SystemExit("--backend gpt_researcher requires --query")
    try:
        from gpt_researcher import GPTResearcher  # type: ignore[import]
    except Exception as exc:
        raise SystemExit(
            "gpt_researcher backend requested but package is not installed. "
            "Install optional dependencies from requirements-research.txt."
        ) from exc

    researcher = GPTResearcher(query=args.query, source_urls=load_urls(args) or None)
    await researcher.conduct_research()
    context = researcher.get_research_context()
    raw_sources = researcher.get_research_sources()
    source_urls = researcher.get_source_urls()

    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, url in enumerate(source_urls or [], start=1):
        text = "\n\n".join(str(item) for item in context if item)
        source = {
            "source_id": stable_id("src", {"url": url}),
            "url": url,
            "title": url,
            "snippet": text[:500],
            "query": args.query,
            "research_subquery": args.query,
            "research_subquery_id": "gpt_researcher",
            "rank": index,
            "source_mode": "gpt_researcher",
            "domain": domain_from_url(url),
            "source_type_detail": classify_source_type(url, url, text),
            "source_quality_score": source_quality_score(url=url, title=url, text=text, query=args.query),
            "retrieved_at": utc_now(),
            "status": "fetched",
        }
        sources.append(source)
        evidence.extend(evidence_from_source(source, text, args))

    if not sources and raw_sources:
        for index, item in enumerate(raw_sources, start=1):
            text = str(item.get("content") or item.get("raw_content") or item)
            url = str(item.get("url") or item.get("href") or f"gpt_researcher_source_{index}")
            source = {
                "source_id": stable_id("src", {"url": url, "index": index}),
                "url": url if url.startswith(("http://", "https://")) else "",
                "title": str(item.get("title") or url),
                "snippet": text[:500],
                "query": args.query,
                "research_subquery": args.query,
                "research_subquery_id": "gpt_researcher",
                "rank": index,
                "source_mode": "gpt_researcher",
                "domain": domain_from_url(url),
                "source_type_detail": classify_source_type(url, str(item.get("title") or ""), text),
                "source_quality_score": source_quality_score(url=url, title=str(item.get("title") or ""), text=text, query=args.query),
                "retrieved_at": utc_now(),
                "status": "fetched",
            }
            sources.append(source)
            evidence.extend(evidence_from_source(source, text, args))

    research_plan = build_research_plan(query=args.query, max_subqueries=1)
    research_plan["backend"] = "gpt_researcher"
    return write_outputs(
        output_dir=output_dir,
        research_plan=research_plan,
        sources=sources,
        evidence=evidence,
        args=args,
    )


def _apply_domain_cap(
    sources: list[dict[str, Any]], cap: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not cap:  # 0 = disabled
        return sources, {}
    from collections import defaultdict
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in sources:
        buckets[domain_from_url(str(s.get("url") or ""))].append(s)
    capped: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for domain, items in buckets.items():
        if len(items) > cap:
            capped[domain] = len(items)
        result.extend(items[:cap])
    return result, capped


def run_native_backend(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    plan = load_json_object(args.plan_file)
    taxonomy = load_json_object(args.taxonomy_file)
    research_plan = build_research_plan(
        query=args.query or "",
        plan=plan,
        taxonomy=taxonomy,
        max_subqueries=args.max_subqueries,
    )

    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if args.query:
        sources.extend(build_web_sources(args, research_plan))
    explicit_urls = load_urls(args)
    if explicit_urls:
        sources.extend(build_explicit_url_sources(args, explicit_urls))
    sources = dedupe_sources(sources)[: args.max_sources]

    sources, domains_capped = _apply_domain_cap(sources, getattr(args, "max_sources_per_domain", 5))

    per_domain_rate = args.per_domain_rate_limit if getattr(args, "per_domain_rate_limit", None) is not None else args.rate_limit
    rate_limiter = RateLimiter(per_domain_seconds=per_domain_rate)

    fetched_sources: list[dict[str, Any]] = []
    for source in sources:
        title, text, error = fetch_source_text(source, args, rate_limiter=rate_limiter)
        source["title"] = title or source.get("title") or source.get("url")
        source["domain"] = domain_from_url(str(source.get("url") or ""))
        source["source_type_detail"] = classify_source_type(str(source.get("url") or ""), title, text)
        source["source_quality_score"] = source_quality_score(
            url=str(source.get("url") or ""),
            title=title,
            snippet=str(source.get("snippet") or ""),
            text=text,
            query=str(source.get("research_subquery") or args.query or ""),
        )
        source["status"] = "error" if error and not text.strip() else "fetched"
        if error:
            source["error"] = error
        fetched_sources.append(source)
        min_sq = getattr(args, "min_source_quality_score", 0.0)
        if min_sq > 0.0 and float(source.get("source_quality_score") or 0.0) < min_sq:
            source["status"] = "filtered_low_quality"
            continue
        if text.strip():
            evidence.extend(evidence_from_source(source, text, args))

    local_sources, local_evidence = collect_local_sources(args)
    fetched_sources.extend(local_sources)
    evidence.extend(local_evidence)
    fetched_sources.sort(key=lambda item: float(item.get("source_quality_score") or 0.0), reverse=True)
    return write_outputs(
        output_dir=output_dir,
        research_plan=research_plan,
        sources=fetched_sources,
        evidence=evidence,
        args=args,
        domains_capped=domains_capped,
    )


def main() -> None:
    args = parse_args()
    if not any([args.query, args.urls, args.url_file, args.paths]):
        raise SystemExit("Provide at least one source mode: --query, --urls, --url-file, or --paths.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) if args.output_dir else WORKSPACE_DIR / f"research_{timestamp}"
    if args.backend == "gpt_researcher":
        summary = asyncio.run(run_gpt_researcher_backend(args, output_dir))
    else:
        summary = run_native_backend(args, output_dir)
    if args.report:
        write_json(args.report, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
