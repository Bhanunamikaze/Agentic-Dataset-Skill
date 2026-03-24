from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .db import CanonicalRecord
from .security import sanitize_record

INSTRUCTION_KEYS = ("instruction", "prompt", "query", "question", "task")
CONTEXT_KEYS = ("context", "input", "background", "system", "notes")
RESPONSE_KEYS = ("response", "output", "answer", "completion", "assistant")
DIFFICULTY_KEYS = ("difficulty", "level")
PERSONA_KEYS = ("persona", "role", "speaker")


def _pick(raw: Mapping[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return default


def _normalize_messages(messages: list[dict[str, Any]]) -> tuple[str, str, str]:
    system_parts: list[str] = []
    prior_turns: list[str] = []
    instruction = ""
    response = ""

    user_messages = [item.get("content", "") for item in messages if item.get("role") == "user"]
    assistant_messages = [item.get("content", "") for item in messages if item.get("role") == "assistant"]

    for message in messages:
        role = message.get("role", "")
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role not in ("user", "assistant"):
            prior_turns.append(f"{role}: {content}")

    if user_messages:
        instruction = str(user_messages[-1]).strip()
        for item in user_messages[:-1]:
            if str(item).strip():
                prior_turns.append(f"user: {item}")
    if assistant_messages:
        response = str(assistant_messages[-1]).strip()
        for item in assistant_messages[:-1]:
            if str(item).strip():
                prior_turns.append(f"assistant: {item}")

    context_parts = system_parts + prior_turns
    context = "\n".join(part for part in context_parts if part).strip()
    return instruction, context, response


def build_record_id(payload: Mapping[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()
    return f"rec_{digest[:16]}"


def coerce_metadata(raw: Mapping[str, Any], source_type: str) -> dict[str, Any]:
    metadata = dict(raw.get("metadata") or {})
    metadata.setdefault("difficulty", str(_pick(raw, DIFFICULTY_KEYS, "unspecified")))
    metadata.setdefault("persona", str(_pick(raw, PERSONA_KEYS, "general")))
    metadata.setdefault("source_type", str(raw.get("source_type", source_type)))
    tags = metadata.get("tags")
    if isinstance(tags, str):
        metadata["tags"] = [item.strip() for item in tags.split(",") if item.strip()]
    elif tags is None:
        metadata["tags"] = []
    return metadata


def build_seed_record(
    *,
    topic: str,
    index: int,
    task_type: str,
    source_type: str = "generated",
) -> CanonicalRecord:
    response = (
        {
            "format": "preference_pair",
            "chosen": "[PENDING_CHOSEN_RESPONSE]",
            "rejected": "[PENDING_REJECTED_RESPONSE]",
        }
        if task_type == "dpo"
        else {"format": "single", "text": "[PENDING_RESPONSE]"}
    )
    payload = {
        "task_type": task_type,
        "instruction": f"Create dataset example {index} for topic: {topic}",
        "context": "",
        "response": response,
    }
    record_id = build_record_id({**payload, "seed_index": index})
    return CanonicalRecord(
        id=record_id,
        task_type=task_type,
        instruction=payload["instruction"],
        context=payload["context"],
        response=response,
        metadata={
            "difficulty": "unspecified",
            "persona": "general",
            "topic": topic,
            "seed_index": index,
            "draft_state": "seed",
            "source_type": source_type,
            "tags": [],
        },
        status="seeded",
        source_type=source_type,
    )


def normalize_record(
    raw: Mapping[str, Any],
    *,
    default_task_type: str = "sft",
    source_type: str = "manual",
    allow_injections: bool = False,
) -> dict[str, Any]:
    record = dict(raw)
    raw_metadata = record.get("metadata") or {}
    effective_allow_injections = allow_injections or bool(record.get("allow_injections")) or bool(
        raw_metadata.get("allow_injections")
    )

    if isinstance(record.get("response"), dict):
        response = dict(record["response"])
        task_type = str(record.get("task_type", default_task_type))
        instruction = str(record.get("instruction", "")).strip()
        context = str(record.get("context", ""))
    elif "chosen" in record and "rejected" in record:
        task_type = "dpo"
        instruction = str(_pick(record, INSTRUCTION_KEYS, "")).strip()
        context = str(_pick(record, CONTEXT_KEYS, ""))
        response = {
            "format": "preference_pair",
            "chosen": str(record.get("chosen", "")).strip(),
            "rejected": str(record.get("rejected", "")).strip(),
        }
    elif isinstance(record.get("messages"), list):
        task_type = str(record.get("task_type", default_task_type))
        instruction, context, output = _normalize_messages(list(record["messages"]))
        response = {"format": "single", "text": output}
    else:
        task_type = str(record.get("task_type", default_task_type))
        instruction = str(_pick(record, INSTRUCTION_KEYS, "")).strip()
        context = str(_pick(record, CONTEXT_KEYS, ""))
        response_text = str(_pick(record, RESPONSE_KEYS, "")).strip()
        response = {"format": "single", "text": response_text}

    normalized = {
        "id": str(record.get("id") or ""),
        "task_type": task_type,
        "instruction": instruction,
        "context": context,
        "response": response,
        "metadata": coerce_metadata(record, source_type),
        "pipeline_status": str(record.get("pipeline_status", "pending")),
        "run_id": record.get("run_id"),
        "status": str(record.get("status", "pending")),
        "source_type": str(record.get("source_type", source_type)),
        "source_uri": record.get("source_uri") or record.get("url"),
        "raw_payload": json.dumps(record, ensure_ascii=True, sort_keys=True),
        "judge_score": record.get("judge_score"),
        "judge_reason": record.get("judge_reason"),
        "error_message": record.get("error_message"),
    }
    normalized = sanitize_record(
        normalized,
        source_type=normalized["source_type"],
        allow_injections=effective_allow_injections,
    )
    if not normalized["id"]:
        normalized["id"] = build_record_id(
            {
                "task_type": normalized["task_type"],
                "instruction": normalized["instruction"],
                "context": normalized["context"],
                "response": normalized["response"],
            }
        )
    return normalized


def row_to_record(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    metadata = json.loads(payload["metadata_json"]) if payload.get("metadata_json") else {}
    response: dict[str, Any]
    if payload.get("response_format") == "preference_pair":
        response = {
            "format": "preference_pair",
            "chosen": payload.get("response_chosen") or "",
            "rejected": payload.get("response_rejected") or "",
        }
    else:
        response = {
            "format": "single",
            "text": payload.get("response_text") or "",
        }

    return {
        "id": payload["id"],
        "task_type": payload["task_type"],
        "instruction": payload["instruction"],
        "context": payload["context"],
        "response": response,
        "metadata": metadata,
        "pipeline_status": payload["pipeline_status"],
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "source_type": payload.get("source_type"),
        "source_uri": payload.get("source_uri"),
        "judge_score": payload.get("judge_score"),
        "judge_reason": payload.get("judge_reason"),
        "error_message": payload.get("error_message"),
    }


def record_text(record: Mapping[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        response_text = "\n".join(
            [
                str(response.get("chosen", "")),
                str(response.get("rejected", "")),
            ]
        )
    else:
        response_text = str(response.get("text", ""))
    return "\n".join(
        [
            str(record.get("instruction", "")),
            str(record.get("context", "")),
            response_text,
        ]
    ).strip()
