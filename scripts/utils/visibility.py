from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .coverage_plan import ensure_string_list, resolve_path

DEFAULT_REPLACEMENT = "[redacted]"


def _parsed_response_payload(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    response = record.get("response")
    if not isinstance(response, Mapping):
        return None
    text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def resolve_visibility_path(record: Mapping[str, Any], path: str) -> Any:
    value = resolve_path(record, path)
    if value is not None:
        return value
    if path.startswith("response."):
        response_payload = _parsed_response_payload(record)
        if response_payload is None:
            return None
        return resolve_path(response_payload, path.split(".", 1)[1])
    return None


def _iter_scalar_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, Mapping):
        items: list[str] = []
        for nested in value.values():
            items.extend(_iter_scalar_strings(nested))
        return items
    if isinstance(value, list):
        items: list[str] = []
        for nested in value:
            items.extend(_iter_scalar_strings(nested))
        return items
    return []


def _field_values(record: Mapping[str, Any], paths: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for item in _iter_scalar_strings(resolve_visibility_path(record, path)):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(item)
    return values


def _value_pattern(value: str, *, case_sensitive: bool) -> re.Pattern[str]:
    escaped = re.escape(value)
    flags = 0 if case_sensitive else re.IGNORECASE
    if re.fullmatch(r"[A-Za-z0-9_]+", value):
        return re.compile(rf"(?<!\w){escaped}(?!\w)", flags)
    return re.compile(escaped, flags)


def sanitize_prompt_text(
    text: str,
    record: Mapping[str, Any],
    config: Mapping[str, Any] | None,
) -> tuple[str, bool]:
    if not text or not isinstance(config, Mapping) or not config:
        return text, False

    case_sensitive = bool(config.get("case_sensitive", False))
    replacement = str(config.get("replacement", DEFAULT_REPLACEMENT))
    prefixes = [
        item.lower()
        for item in ensure_string_list(
            config.get("remove_line_prefixes") or config.get("drop_line_prefixes")
        )
    ]

    line_removal = config.get("remove_lines_with_fields") or {}
    line_paths = []
    line_min_hits = 0
    if isinstance(line_removal, Mapping):
        line_paths = ensure_string_list(line_removal.get("paths") or line_removal.get("fields"))
        line_min_hits = max(1, int(line_removal.get("min_hits", 1))) if line_paths else 0

    redact_paths = ensure_string_list(
        config.get("redact_field_values") or config.get("redact_fields")
    )

    line_patterns = [
        _value_pattern(value, case_sensitive=case_sensitive)
        for value in _field_values(record, line_paths)
    ]
    redact_patterns = [
        _value_pattern(value, case_sensitive=case_sensitive)
        for value in _field_values(record, redact_paths)
    ]

    lines_out: list[str] = []
    modified = False
    previous_blank = False

    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped and prefixes and any(lowered.startswith(prefix) for prefix in prefixes):
            modified = True
            continue
        if stripped and line_patterns:
            hit_count = sum(1 for pattern in line_patterns if pattern.search(line))
            if hit_count >= line_min_hits:
                modified = True
                continue

        updated = line
        for pattern in redact_patterns:
            updated, replacements = pattern.subn(replacement, updated)
            if replacements:
                modified = True

        blank = not updated.strip()
        if blank and previous_blank:
            modified = True
            continue
        lines_out.append(updated)
        previous_blank = blank

    sanitized = "\n".join(lines_out).strip()
    if sanitized != text.strip():
        modified = True
    return sanitized, modified


def sanitize_record_for_model_visibility(
    record: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    visibility = plan.get("model_visibility") or {}
    if not isinstance(visibility, Mapping) or not visibility:
        return dict(record), {"instruction": False, "context": False}

    sanitized = dict(record)
    instruction, instruction_modified = sanitize_prompt_text(
        str(record.get("instruction", "")),
        record,
        visibility.get("instruction") if isinstance(visibility.get("instruction"), Mapping) else {},
    )
    context, context_modified = sanitize_prompt_text(
        str(record.get("context", "")),
        record,
        visibility.get("context") if isinstance(visibility.get("context"), Mapping) else {},
    )
    sanitized["instruction"] = instruction
    sanitized["context"] = context
    return sanitized, {"instruction": instruction_modified, "context": context_modified}


def sanitize_records_for_model_visibility(
    records: list[dict[str, Any]],
    plan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    visibility = plan.get("model_visibility") or {}
    if not isinstance(visibility, Mapping) or not visibility:
        return list(records), {
            "enabled": False,
            "instruction_modified": 0,
            "context_modified": 0,
            "records_modified": 0,
        }

    sanitized_records: list[dict[str, Any]] = []
    instruction_modified = 0
    context_modified = 0
    records_modified = 0

    for record in records:
        sanitized, changes = sanitize_record_for_model_visibility(record, plan)
        sanitized_records.append(sanitized)
        if changes["instruction"]:
            instruction_modified += 1
        if changes["context"]:
            context_modified += 1
        if changes["instruction"] or changes["context"]:
            records_modified += 1

    return sanitized_records, {
        "enabled": True,
        "instruction_modified": instruction_modified,
        "context_modified": context_modified,
        "records_modified": records_modified,
    }
