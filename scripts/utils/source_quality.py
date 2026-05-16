from __future__ import annotations

import math
import re
import urllib.parse
from collections import Counter
from typing import Any

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)
LOW_VALUE_HINTS = (
    "cookie",
    "privacy policy",
    "terms of service",
    "subscribe",
    "advertisement",
    "sign up",
)
HIGH_SIGNAL_DOMAINS = (
    "github.com",
    "stackoverflow.com",
    "stackexchange.com",
    "docs.",
    "developer.",
    "cve.org",
    "nvd.nist.gov",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(str(text or "").lower())


def domain_from_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or ""))
    return parsed.netloc.lower().removeprefix("www.")


def classify_source_type(url: str, title: str = "", text: str = "") -> str:
    joined = " ".join([url, title, text[:500]]).lower()
    domain = domain_from_url(url)
    if "github.com" in domain:
        return "code_or_issue_tracker"
    if "stackoverflow" in domain or "stackexchange" in domain or "forum" in joined:
        return "forum_or_qna"
    if "docs" in domain or "/docs" in joined or "documentation" in joined:
        return "documentation"
    if "cve" in domain or "nvd.nist" in domain:
        return "vulnerability_database"
    if "arxiv" in domain or "pubmed" in domain or "paper" in joined:
        return "research_paper"
    if any(word in joined for word in ("blog", "case study", "postmortem")):
        return "article_or_case_study"
    return "web_page"


def boilerplate_penalty(text: str) -> float:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return 0.35
    hits = sum(1 for hint in LOW_VALUE_HINTS if hint in lowered)
    return min(0.35, hits * 0.07)


def lexical_relevance(query: str, title: str, snippet: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    source_tokens = set(tokenize(" ".join([title, snippet, text[:2000]])))
    if not source_tokens:
        return 0.0
    return len(query_tokens & source_tokens) / len(query_tokens)


def source_quality_score(
    *,
    url: str = "",
    title: str = "",
    snippet: str = "",
    text: str = "",
    query: str = "",
) -> float:
    length = len(str(text or snippet or ""))
    length_score = min(1.0, math.log10(max(length, 1)) / 4.0)
    relevance_score = lexical_relevance(query, title, snippet, text)
    domain = domain_from_url(url)
    domain_score = 0.75 if any(marker in domain for marker in HIGH_SIGNAL_DOMAINS) else 0.45
    provenance_score = 1.0 if url.startswith(("http://", "https://")) else 0.65
    score = (
        0.35 * length_score
        + 0.30 * relevance_score
        + 0.20 * domain_score
        + 0.15 * provenance_score
        - boilerplate_penalty(text or snippet)
    )
    return round(max(0.0, min(1.0, score)), 4)


def source_distribution(sources: list[dict[str, Any]]) -> dict[str, Any]:
    domains = Counter(str(item.get("domain") or domain_from_url(str(item.get("url") or ""))) for item in sources)
    types = Counter(str(item.get("source_type_detail") or "unknown") for item in sources)
    return {
        "unique_domains": len([key for key in domains if key]),
        "domain_counts": dict(sorted(domains.items(), key=lambda item: (-item[1], item[0]))),
        "source_type_counts": dict(sorted(types.items(), key=lambda item: (-item[1], item[0]))),
    }
