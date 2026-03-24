from __future__ import annotations

import re
from typing import Any

CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
UNTRUSTED_SOURCE_TYPES = {"url_reference", "raw_dataset", "internet_research"}
PROMPT_INJECTION_PATTERNS = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,80}\b(previous|prior|above|earlier|system)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role_override",
        re.compile(
            r"\byou are\b.{0,80}\b(system|assistant|judge|chatgpt|claude|codex)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt_leak_request",
        re.compile(
            r"\b(reveal|print|show|leak)\b.{0,80}\b(system prompt|hidden instructions)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "chat_control_token",
        re.compile(r"<\|/?(?:system|assistant|user)\|>", re.IGNORECASE),
    ),
)


def sanitize_text(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    cleaned = CONTROL_CHAR_PATTERN.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    return cleaned, cleaned != value


def sanitize_record(
    record: dict[str, Any],
    *,
    source_type: str,
    allow_injections: bool = False,
) -> dict[str, Any]:
    sanitized = dict(record)
    metadata = dict(sanitized.get("metadata") or {})
    changed = False

    for key in ("instruction", "context", "source_uri"):
        cleaned, field_changed = sanitize_text(sanitized.get(key))
        if field_changed:
            sanitized[key] = cleaned
            changed = True

    response = dict(sanitized.get("response") or {})
    response_fields = (
        ("text", "response.text"),
        ("chosen", "response.chosen"),
        ("rejected", "response.rejected"),
    )
    text_fields: list[tuple[str, str]] = []
    for field_name, label in response_fields:
        cleaned, field_changed = sanitize_text(response.get(field_name))
        if field_changed:
            response[field_name] = cleaned
            changed = True
        if isinstance(response.get(field_name), str):
            text_fields.append((label, str(response.get(field_name))))

    if response:
        sanitized["response"] = response

    text_fields.extend(
        [
            ("instruction", str(sanitized.get("instruction", ""))),
            ("context", str(sanitized.get("context", ""))),
        ]
    )

    flags: set[str] = set()
    if source_type in UNTRUSTED_SOURCE_TYPES:
        metadata["untrusted_ingestion"] = True
        if allow_injections:
            metadata["allow_injections"] = True
        else:
            for label, text in text_fields:
                for flag_name, pattern in PROMPT_INJECTION_PATTERNS:
                    if pattern.search(text):
                        flags.add(f"{label}:{flag_name}")

    if changed:
        metadata["sanitization_applied"] = True
    if flags:
        metadata["security_flags"] = sorted(flags)
        metadata["requires_manual_review"] = True

    sanitized["metadata"] = metadata
    return sanitized
