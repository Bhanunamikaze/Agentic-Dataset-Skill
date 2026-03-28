from __future__ import annotations

from typing import Any

from .c_family import parse_c_family_corpus
from .html import parse_article_corpus


def parse_discovered_files(
    files: list[dict[str, Any]],
    *,
    bundle_max_chars: int = 12000,
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    warnings: list[str] = []

    c_family_files = [
        item for item in files
        if str(item.get("metadata", {}).get("parser_key")) == "c_family"
    ]
    article_files = [
        item for item in files
        if str(item.get("metadata", {}).get("parser_key")) == "article"
    ]

    if c_family_files:
        parsed = parse_c_family_corpus(c_family_files, bundle_max_chars=bundle_max_chars)
        units.extend(parsed["units"])
        relations.extend(parsed["relations"])
        bundles.extend(parsed["bundles"])
        warnings.extend(parsed["warnings"])

    if article_files:
        parsed = parse_article_corpus(article_files, bundle_max_chars=bundle_max_chars)
        units.extend(parsed["units"])
        relations.extend(parsed["relations"])
        bundles.extend(parsed["bundles"])
        warnings.extend(parsed["warnings"])

    return {
        "units": units,
        "relations": relations,
        "bundles": bundles,
        "warnings": warnings,
    }
