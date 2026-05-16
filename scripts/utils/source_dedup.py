from __future__ import annotations

import re
import urllib.parse
from typing import Any, Mapping

_TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_KEYS
    ]
    query = urllib.parse.urlencode(sorted(query_items), doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def dedupe_sources(sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for source in sources:
        payload = dict(source)
        uri = str(payload.get("url") or payload.get("source_uri") or payload.get("path") or "")
        key = canonicalize_url(uri) if uri.startswith(("http://", "https://")) else uri
        if not key or key in seen:
            continue
        payload["canonical_uri"] = key
        seen.add(key)
        unique.append(payload)
    return unique
