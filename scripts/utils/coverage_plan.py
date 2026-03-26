from __future__ import annotations

import json
from itertools import product
from typing import Any, Iterable, Mapping


def load_plan(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Coverage plan must be a JSON object")
    return payload


def ensure_string_list(values: Iterable[Any] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            items.append(text)
    return items


def resolve_path(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not [item for item in value if not is_missing_value(item)]
    if isinstance(value, dict):
        return not value
    return False


def values_for_field(payload: Mapping[str, Any], field_path: str, *, missing_token: str = "__missing__") -> list[str]:
    value = resolve_path(payload, field_path)
    if is_missing_value(value):
        return [missing_token]
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if not is_missing_value(item)]
        return normalized or [missing_token]
    return [str(value)]


def bucket_keys_for_fields(
    payload: Mapping[str, Any],
    fields: list[str],
    *,
    separator: str = "::",
    missing_token: str = "__missing__",
) -> list[str]:
    if not fields:
        return []
    value_lists = [values_for_field(payload, field, missing_token=missing_token) for field in fields]
    return [separator.join(combo) for combo in product(*value_lists)]


def plan_required_fields(plan: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    for item in ensure_string_list(plan.get("required_fields")):
        fields.append(item)
    for item in ensure_string_list(plan.get("required_metadata_fields")):
        fields.append(item if item.startswith("metadata.") else f"metadata.{item}")
    provenance = plan.get("provenance") or {}
    if isinstance(provenance, Mapping):
        field = str(provenance.get("field", "")).strip()
        if field:
            fields.append(field)

    unique: list[str] = []
    seen: set[str] = set()
    for field in fields:
        if field in seen:
            continue
        unique.append(field)
        seen.add(field)
    return unique
