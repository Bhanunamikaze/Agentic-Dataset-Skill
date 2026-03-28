from __future__ import annotations

import email
import re
from email import policy
from pathlib import Path
from typing import Any

from .base import build_bundle, build_relation, build_unit

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency fallback
    BeautifulSoup = None


def _truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 17)].rstrip() + "\n...[truncated]"


def _infer_snippet_language(class_names: list[str], snippet: str) -> str:
    combined = " ".join(class_names).lower()
    snippet_lower = snippet.lower()
    if any(token in combined for token in ("cpp", "c++", "language-cpp", "language-c")):
        return "c_cpp"
    if "#include" in snippet_lower or "std::" in snippet_lower or "printf(" in snippet_lower:
        return "c_cpp"
    if "<html" in snippet_lower or "</div>" in snippet_lower:
        return "html"
    return "unknown"


def _decode_mhtml(path: str) -> tuple[str, str]:
    message = email.message_from_bytes(Path(path).read_bytes(), policy=policy.default)
    text_html = ""
    text_plain = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            try:
                payload = part.get_content()
            except Exception:
                payload = ""
            if content_type == "text/html" and not text_html:
                text_html = str(payload)
            elif content_type == "text/plain" and not text_plain:
                text_plain = str(payload)
    else:
        payload = message.get_content()
        if message.get_content_type() == "text/html":
            text_html = str(payload)
        else:
            text_plain = str(payload)
    return text_html, text_plain


def _html_snippet_bundles(
    file_record: dict[str, Any],
    *,
    bundle_max_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    warnings: list[str] = []
    content = str(file_record.get("content") or "")

    if str(file_record.get("kind")) == "mhtml_document":
        html_content, plain_text = _decode_mhtml(str(file_record["source_path"]))
        content = html_content or plain_text or content

    if BeautifulSoup is None:
        warnings.append(f"BeautifulSoup unavailable for {file_record['source_path']}")
        snippet_text = _truncate(content, bundle_max_chars)
        bundles.append(
            build_bundle(
                kind="article_context",
                source_path=str(file_record["source_path"]),
                title=str(file_record.get("title") or Path(str(file_record["source_path"])).name),
                language=str(file_record.get("language") or "html"),
                content=snippet_text,
                metadata={"bundle_type": "article", "snippet_count": 0},
                stable_payload={"source_path": str(file_record["source_path"]), "content": snippet_text},
            )
        )
        return units, relations, bundles, warnings

    soup = BeautifulSoup(content, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    title = title or str(file_record.get("title") or Path(str(file_record["source_path"])).name)

    seen_nodes: set[int] = set()
    snippet_nodes = []
    for node in soup.find_all(["pre", "code"]):
        if node.name == "code" and node.parent and node.parent.name == "pre":
            continue
        node_id = id(node)
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        text = node.get_text("\n", strip=True)
        if not text or len(text) < 12:
            continue
        snippet_nodes.append(node)

    for index, node in enumerate(snippet_nodes, start=1):
        snippet_text = node.get_text("\n", strip=True)
        heading_node = node.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        previous_blocks = [
            item.get_text(" ", strip=True)
            for item in node.find_all_previous(["p", "li"], limit=2)
            if item.get_text(" ", strip=True)
        ]
        previous_blocks.reverse()
        next_blocks = [
            item.get_text(" ", strip=True)
            for item in node.find_all_next(["p", "li"], limit=2)
            if item.get_text(" ", strip=True)
        ]
        class_names = list(node.get("class") or [])
        snippet_language = _infer_snippet_language(class_names, snippet_text)

        units.append(
            build_unit(
                kind="article_code_snippet",
                source_path=str(file_record["source_path"]),
                title=f"{title} snippet {index}",
                language=snippet_language,
                content=_truncate(snippet_text, 3000),
                metadata={
                    "heading": heading_node.get_text(" ", strip=True) if heading_node else "",
                    "document_title": title,
                    "snippet_index": index,
                    "file_id": file_record["id"],
                    "class_names": class_names,
                },
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "index": index,
                    "snippet": snippet_text,
                },
            )
        )
        relations.append(
            build_relation(
                kind="snippet_from_document",
                source_path=str(file_record["source_path"]),
                metadata={
                    "document_title": title,
                    "snippet_index": index,
                },
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "snippet_index": index,
                },
            )
        )

        bundle_content = "\n\n".join(
            section for section in [
                f"Document Title: {title}",
                f"Section Heading: {heading_node.get_text(' ', strip=True) if heading_node else ''}",
                "Before:\n" + "\n".join(previous_blocks) if previous_blocks else "",
                "Code Snippet:\n" + snippet_text,
                "After:\n" + "\n".join(next_blocks) if next_blocks else "",
            ]
            if section.strip()
        )
        bundles.append(
            build_bundle(
                kind="article_snippet_context",
                source_path=str(file_record["source_path"]),
                title=f"{title} snippet {index}",
                language=snippet_language,
                content=_truncate(bundle_content, bundle_max_chars),
                metadata={
                    "bundle_type": "article",
                    "document_title": title,
                    "heading": heading_node.get_text(" ", strip=True) if heading_node else "",
                    "snippet_index": index,
                    "snippet_language": snippet_language,
                    "before_context": previous_blocks,
                    "after_context": next_blocks,
                },
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "snippet_index": index,
                    "title": title,
                },
            )
        )

    if not bundles:
        text = soup.get_text("\n", strip=True)
        bundles.append(
            build_bundle(
                kind="article_context",
                source_path=str(file_record["source_path"]),
                title=title,
                language=str(file_record.get("language") or "html"),
                content=_truncate(text, bundle_max_chars),
                metadata={
                    "bundle_type": "article",
                    "document_title": title,
                    "snippet_count": 0,
                },
                stable_payload={"source_path": str(file_record["source_path"]), "title": title},
            )
        )

    return units, relations, bundles, warnings


def _markdown_or_text_bundles(
    file_record: dict[str, Any],
    *,
    bundle_max_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    content = str(file_record.get("content") or "")
    title = str(file_record.get("title") or Path(str(file_record["source_path"])).name)
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    warnings: list[str] = []

    heading_positions: list[tuple[int, str]] = []
    for match in re.finditer(r"^(#{1,6})\s+(.*)$", content, re.MULTILINE):
        heading_positions.append((match.start(), match.group(2).strip()))

    code_blocks = list(
        re.finditer(
            r"```(?P<lang>[A-Za-z0-9_+-]*)\n(?P<code>.*?)```",
            content,
            re.DOTALL,
        )
    )
    for index, match in enumerate(code_blocks, start=1):
        heading = ""
        for position, heading_text in heading_positions:
            if position <= match.start():
                heading = heading_text
            else:
                break
        code = match.group("code").strip()
        lang = match.group("lang").strip() or _infer_snippet_language([], code)
        before = _truncate(content[max(0, match.start() - 300):match.start()], 300)
        after = _truncate(content[match.end():match.end() + 300], 300)
        units.append(
            build_unit(
                kind="article_code_snippet",
                source_path=str(file_record["source_path"]),
                title=f"{title} snippet {index}",
                language=lang,
                content=_truncate(code, 3000),
                metadata={
                    "heading": heading,
                    "document_title": title,
                    "snippet_index": index,
                    "file_id": file_record["id"],
                },
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "snippet_index": index,
                    "code": code,
                },
            )
        )
        relations.append(
            build_relation(
                kind="snippet_from_document",
                source_path=str(file_record["source_path"]),
                metadata={"document_title": title, "snippet_index": index},
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "snippet_index": index,
                },
            )
        )
        bundle_text = "\n\n".join(
            section for section in [
                f"Document Title: {title}",
                f"Section Heading: {heading}",
                "Before:\n" + before if before.strip() else "",
                "Code Snippet:\n" + code,
                "After:\n" + after if after.strip() else "",
            ]
            if section.strip()
        )
        bundles.append(
            build_bundle(
                kind="article_snippet_context",
                source_path=str(file_record["source_path"]),
                title=f"{title} snippet {index}",
                language=lang,
                content=_truncate(bundle_text, bundle_max_chars),
                metadata={
                    "bundle_type": "article",
                    "document_title": title,
                    "heading": heading,
                    "snippet_index": index,
                    "snippet_language": lang,
                },
                stable_payload={
                    "source_path": str(file_record["source_path"]),
                    "snippet_index": index,
                    "title": title,
                },
            )
        )

    if not bundles:
        bundles.append(
            build_bundle(
                kind="article_context",
                source_path=str(file_record["source_path"]),
                title=title,
                language=str(file_record.get("language") or "text"),
                content=_truncate(content, bundle_max_chars),
                metadata={"bundle_type": "article", "document_title": title, "snippet_count": 0},
                stable_payload={"source_path": str(file_record["source_path"]), "title": title},
            )
        )

    return units, relations, bundles, warnings


def parse_article_corpus(
    files: list[dict[str, Any]],
    *,
    bundle_max_chars: int = 12000,
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    warnings: list[str] = []

    for item in files:
        language = str(item.get("language") or "")
        if language in {"html", "mhtml"}:
            parsed_units, parsed_relations, parsed_bundles, parsed_warnings = _html_snippet_bundles(
                item,
                bundle_max_chars=bundle_max_chars,
            )
        else:
            parsed_units, parsed_relations, parsed_bundles, parsed_warnings = _markdown_or_text_bundles(
                item,
                bundle_max_chars=bundle_max_chars,
            )

        units.extend(parsed_units)
        relations.extend(parsed_relations)
        bundles.extend(parsed_bundles)
        warnings.extend(parsed_warnings)

    return {
        "units": units,
        "relations": relations,
        "bundles": bundles,
        "warnings": sorted(dict.fromkeys(warnings)),
    }
