from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT_DIR / "resources" / "internal-schema" / "canonical_schema.json"
PIPELINE_STATUSES = {"pending", "pass", "fail", "rewrite"}
TASK_TYPES = {"sft", "dpo"}


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_record(record: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return basic_validate_record(record)

    validator = Draft202012Validator(load_schema())
    errors = [error.message for error in validator.iter_errors(project_record_for_schema(record))]
    if errors:
        return errors
    return basic_validate_record(record)


def project_record_for_schema(record: dict[str, Any]) -> dict[str, Any]:
    schema = load_schema()
    allowed_keys = set(schema.get("properties", {}).keys())
    projected = {key: record[key] for key in allowed_keys if key in record}

    lineage = dict(projected.get("lineage") or {})
    if record.get("run_id") is not None:
        lineage.setdefault("run_id", record.get("run_id"))

    parent_id = ""
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        parent_id = str(metadata.get("parent_id") or "")
    if parent_id:
        lineage.setdefault("parent_id", parent_id)

    source_uri = record.get("source_uri")
    if isinstance(source_uri, str) and source_uri:
        lineage.setdefault("source_path", source_uri)

    if lineage:
        projected["lineage"] = lineage

    return projected


def basic_validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    required_fields = (
        "id",
        "task_type",
        "instruction",
        "context",
        "response",
        "metadata",
        "pipeline_status",
    )
    for field in required_fields:
        if field not in record:
            errors.append(f"Missing required field: {field}")

    if record.get("task_type") not in TASK_TYPES:
        errors.append("task_type must be either 'sft' or 'dpo'")

    response = record.get("response")
    if not isinstance(response, dict):
        errors.append("response must be an object")
        return errors

    response_format = response.get("format")
    if response_format == "single":
        if not isinstance(response.get("text"), str) or not response.get("text", "").strip():
            errors.append("single-format responses must include non-empty response.text")
    elif response_format == "preference_pair":
        chosen = response.get("chosen")
        rejected = response.get("rejected")
        if not isinstance(chosen, str) or not chosen.strip():
            errors.append("preference_pair responses must include non-empty response.chosen")
        if not isinstance(rejected, str) or not rejected.strip():
            errors.append("preference_pair responses must include non-empty response.rejected")
    else:
        errors.append("response.format must be 'single' or 'preference_pair'")

    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
    else:
        for key in ("difficulty", "persona"):
            value = metadata.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"metadata.{key} must be a non-empty string")

    if record.get("pipeline_status") not in PIPELINE_STATUSES:
        errors.append("pipeline_status must be pending, pass, fail, or rewrite")

    instruction = record.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        errors.append("instruction must be a non-empty string")

    context = record.get("context")
    if not isinstance(context, str):
        errors.append("context must be a string")

    return errors


def validate_flat_export_schema(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if not isinstance(schema, dict):
        return ["flat export schema must be a JSON object"]

    name = schema.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("schema.name must be a non-empty string")

    if schema.get("mode") != "flat":
        errors.append("schema.mode must be 'flat'")

    columns = schema.get("columns")
    if not isinstance(columns, list) or not columns:
        errors.append("schema.columns must be a non-empty list")
        return errors

    seen_names: set[str] = set()
    for index, column in enumerate(columns):
        if not isinstance(column, dict):
            errors.append(f"schema.columns[{index}] must be an object")
            continue

        column_name = column.get("name")
        source = column.get("source")

        if not isinstance(column_name, str) or not column_name.strip():
            errors.append(f"schema.columns[{index}].name must be a non-empty string")
        elif column_name in seen_names:
            errors.append(f"schema.columns[{index}].name duplicates '{column_name}'")
        else:
            seen_names.add(column_name)

        if not isinstance(source, str) or not source.strip():
            errors.append(f"schema.columns[{index}].source must be a non-empty string")

    return errors


def load_flat_export_schema(path: Path | str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    errors = validate_flat_export_schema(schema)
    if errors:
        raise ValueError("; ".join(errors))
    return schema
