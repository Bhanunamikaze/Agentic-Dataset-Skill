from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import normalize_record, row_to_record
from scripts.utils.coverage_plan import (
    ensure_string_list,
    is_missing_value,
    load_plan,
    plan_required_fields,
    resolve_path,
    section_is_blocking,
    values_for_field,
)
from scripts.utils.db import (
    fetch_records_by_status,
    get_connection,
    initialize_database,
    upsert_record,
    upsert_run,
)
from scripts.utils.files import load_records, write_json
from scripts.utils.security import resolve_allow_injections
from scripts.utils.schema import validate_record
from scripts.utils.benchmark_guard import benchmark_contamination_errors
from scripts.utils.code_quality import code_quality_errors
from scripts.utils.dpo_quality import dpo_pair_errors

REFUSAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bi cannot\b",
        r"\bi can'?t\b",
        r"\bi will not\b",
        r"\bi apologize, but\b",
        r"\bagainst my ethical guidelines\b",
        r"\bas an ai assistant\b",
        r"\bas an ai language model\b",
        r"\bi am unable to comply\b",
        r"\bi cannot fulfill this\b",
        r"\bi can'?t help with that\b",
        r"\bi must refuse\b",
    )
]
PLACEHOLDER_PATTERN = re.compile(r"\[PENDING_[A-Z_]+\]", re.IGNORECASE)

# Anchor refusal-pattern matching to the first 200 characters of the response.
# Real refusals always begin there; matching anywhere caused false positives
# on legitimate sentences like "the function cannot return None" or
# "I can't decide between these two approaches".
REFUSAL_PREFIX_LIMIT = 200

# Metadata markers that mean the user is intentionally training the model on
# refusals, safety classifications, or jailbreak detection. Skip the refusal
# regex on those records so we don't quarantine the dataset they asked for.
_REFUSAL_EXEMPT_MARKERS = (
    "refusal",
    "safety",
    "classification",
    "decline",
    "jailbreak",
    "red_team",
    "red-team",
    "moderation",
)

# Sub-skills/seed-generator.md mandates dropping trope openers. The judge
# routinely misses them, so we catch them deterministically when the plan
# enables it.
_TROPE_OPENERS = (
    "as an ai",
    "as a language model",
    "as a large language model",
    "certainly!",
    "of course!",
    "sure, here",
    "here is the",
    "here's the",
    "here is your",
    "here's your",
    "in summary,",
    "i hope this helps",
    "great question",
    "absolutely!",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run heuristic verification and optional review-file adjudication."
    )
    parser.add_argument("--input", help="Optional JSON, JSONL, or CSV file to verify directly.")
    parser.add_argument(
        "--review-file",
        help="Optional JSON, JSONL, or CSV file keyed by record id with score, reason, and pass/fail status.",
    )
    parser.add_argument(
        "--plan-file",
        help="Optional coverage/quality plan used to enforce required fields and provenance rules.",
    )
    parser.add_argument(
        "--evidence-file",
        help="Optional research evidence.jsonl file used to validate metadata.evidence_ids.",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Require evidence IDs for every record checked, regardless of source_origin.",
    )
    parser.add_argument(
        "--from-status",
        action="append",
        default=[],
        help="Statuses to verify from the SQLite state when --input is not used. Repeatable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of records to verify from SQLite mode.",
    )
    parser.add_argument("--source-run-id", help="Filter verification to a specific source run id.")
    parser.add_argument("--run-id", help="Optional run identifier. Defaults to a generated UUID.")
    parser.add_argument(
        "--user-query",
        default="dataset verify",
        help="Original user request or run description.",
    )
    parser.add_argument(
        "--tool-context",
        default="generic",
        help="Originating tool context, for example codex, claude, or antigravity.",
    )
    parser.add_argument(
        "--source-type",
        default="generated",
        help="Source type metadata for imported records when --input is used.",
    )
    allow_group = parser.add_mutually_exclusive_group()
    allow_group.add_argument(
        "--allow-injections",
        dest="allow_injections",
        action="store_true",
        help="Allow prompt-injection and jailbreak-like strings during direct file import for intentional adversarial-security datasets.",
    )
    allow_group.add_argument(
        "--enforce-security-flags",
        dest="allow_injections",
        action="store_false",
        help="Keep prompt-injection flagging enabled, even for security or jailbreak dataset requests.",
    )
    parser.set_defaults(allow_injections=None)
    parser.add_argument(
        "--min-instruction-length",
        type=int,
        default=12,
        help="Minimum instruction length before failing heuristics.",
    )
    parser.add_argument(
        "--min-response-length",
        type=int,
        default=12,
        help="Minimum response length before failing heuristics.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def response_texts(record: dict[str, Any]) -> list[str]:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return [str(response.get("chosen", "")), str(response.get("rejected", ""))]
    return [str(response.get("text", ""))]


def primary_response_text(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return str(response.get("chosen") or response.get("rejected") or "")
    return str(response.get("text", ""))


def load_evidence_map(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    evidence: dict[str, dict[str, Any]] = {}
    for row in load_records(path):
        evidence_id = row.get("evidence_id") or row.get("id")
        if evidence_id:
            evidence[str(evidence_id)] = dict(row)
    return evidence


def record_evidence_ids(record: dict[str, Any]) -> list[str]:
    metadata = record.get("metadata") or {}
    value = metadata.get("evidence_ids") or metadata.get("evidence_id") or []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def evidence_required(record: dict[str, Any], args: argparse.Namespace, plan: dict[str, Any]) -> bool:
    if getattr(args, "require_evidence", False):
        return True
    metadata = record.get("metadata") or {}
    if metadata.get("source_origin") == "real_world":
        grounding = plan.get("grounding") or {}
        research = plan.get("research") or {}
        if grounding.get("require_evidence_ids") or research.get("minimum_evidence_linked_share"):
            return True
    return False


def grounding_errors(
    record: dict[str, Any],
    args: argparse.Namespace,
    plan: dict[str, Any],
    evidence_map: dict[str, dict[str, Any]] | None,
) -> list[str]:
    evidence_map = evidence_map or {}
    if not evidence_required(record, args, plan):
        return []
    ids = record_evidence_ids(record)
    if not ids:
        return ["real-world/grounded record is missing metadata.evidence_ids"]
    if not evidence_map:
        return []
    missing = [item for item in ids if item not in evidence_map]
    if missing:
        return ["metadata.evidence_ids reference unknown evidence chunks: " + ", ".join(missing)]
    return []


def _refusal_exempt(metadata: dict[str, Any]) -> bool:
    """Records explicitly about refusal/safety/classification should not be
    flagged for containing refusal phrases — those are the labels."""
    haystack_parts = [
        str(metadata.get("intent") or ""),
        str(metadata.get("label") or ""),
        str(metadata.get("task_label") or ""),
        str(metadata.get("category") or ""),
        str(metadata.get("response_shape") or ""),
    ]
    haystack = " ".join(haystack_parts).lower()
    return any(marker in haystack for marker in _REFUSAL_EXEMPT_MARKERS)


def _refusal_match(text: str) -> re.Pattern[str] | None:
    head = text.strip()[:REFUSAL_PREFIX_LIMIT]
    if not head:
        return None
    for pattern in REFUSAL_PATTERNS:
        if pattern.search(head):
            return pattern
    return None


def trope_opener_errors(record: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """Fail records whose response begins with a known LLM trope opener.

    Enabled only when the plan sets quality_filter.anti_trope=true so existing
    corpora are not retroactively broken; production_quality_plan.json turns
    this on by default."""
    config = plan.get("quality_filter") or {}
    if not isinstance(config, dict) or not config.get("anti_trope"):
        return []
    errors: list[str] = []
    for text in response_texts(record):
        head = text.strip().lower()
        if not head:
            continue
        for marker in _TROPE_OPENERS:
            if head.startswith(marker):
                errors.append(f"response begins with trope opener: {marker!r}")
                break
    return errors


def infer_intent_type(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") or {}
    combined = " ".join(
        str(metadata.get(key, "")) for key in ("intent", "task_type", "response_shape", "label")
    ).lower()
    instruction = str(record.get("instruction") or "").lower()
    if "classification" in combined or metadata.get("label"):
        return "classification"
    if "code_review" in combined or "review" in instruction and "code" in instruction:
        return "code_review"
    if "code" in combined or "write" in instruction and ("function" in instruction or "script" in instruction):
        return "code_generation"
    if "regex" in combined or "regex" in instruction:
        return "regex"
    if "explain" in instruction or "tutorial" in combined:
        return "explanation"
    return "general"


def task_relative_errors(record: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    config = plan.get("quality_filter") or {}
    if not isinstance(config, dict) or not config.get("task_relative_minimums"):
        return []
    text = primary_response_text(record).strip()
    words = [item for item in re.findall(r"\w+", text) if item]
    intent = infer_intent_type(record)
    if intent == "classification":
        return []
    if intent == "regex" and len(text) < 5:
        return ["regex/one-liner response is too short"]
    if intent == "code_review" and len(words) < 50:
        return ["code-review response is below task-relative minimum of 50 words"]
    if intent == "explanation" and len(words) < 80:
        return ["explanation/tutorial response is below task-relative minimum of 80 words"]
    if intent == "code_generation" and text.count("\n") < 4 and len(words) < 25:
        return ["code-generation response is too short for the inferred task"]
    return []


def _python_blocks(text: str) -> list[str]:
    pattern = re.compile(r"```(?:python|py)\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    return [match.group(1).strip() for match in pattern.finditer(text)]


def syntax_errors(record: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    config = plan.get("syntax_checks") or {}
    if not isinstance(config, dict) or not config:
        return []
    errors: list[str] = []
    text = primary_response_text(record).strip()
    instruction = str(record.get("instruction") or "").lower()
    metadata = record.get("metadata") or {}
    if config.get("json") and ("json" in instruction or metadata.get("response_format") == "json"):
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"response is not valid JSON: {exc.msg}")
    if config.get("python"):
        blocks = _python_blocks(text)
        for index, block in enumerate(blocks, start=1):
            try:
                ast.parse(block)
            except SyntaxError as exc:
                errors.append(f"python code block {index} has syntax error: {exc.msg}")
    return errors


def heuristic_errors(record: dict[str, Any], args: argparse.Namespace, plan: dict[str, Any] | None = None, evidence_map: dict[str, dict[str, Any]] | None = None) -> list[str]:
    errors = validate_record(record)

    instruction = str(record.get("instruction", "")).strip()
    metadata = dict(record.get("metadata") or {})
    refusal_exempt = _refusal_exempt(metadata)
    if str(record.get("status", "")).strip() == "collected":
        errors.append("raw collected source chunk must be converted into a training example before verification")
    if len(instruction) < args.min_instruction_length:
        errors.append("instruction is too short for a stable training example")
    if metadata.get("rewrite_required"):
        errors.append("record is a metadata-only variant and must be rewritten before verification")

    for text in response_texts(record):
        stripped = text.strip()
        if len(stripped) < args.min_response_length:
            errors.append("response is too short for a stable training example")
        if PLACEHOLDER_PATTERN.search(stripped):
            errors.append("response still contains pending placeholder markers")
        if not refusal_exempt:
            match = _refusal_match(stripped)
            if match is not None:
                errors.append(f"response matched refusal pattern: {match.pattern}")

    plan = plan or {}
    errors.extend(grounding_errors(record, args, plan, evidence_map))
    errors.extend(task_relative_errors(record, plan))
    errors.extend(syntax_errors(record, plan))
    errors.extend(trope_opener_errors(record, plan))
    errors.extend(code_quality_errors(record, plan))
    errors.extend(dpo_pair_errors(record, plan))
    errors.extend(benchmark_contamination_errors(record, plan))
    for field in plan_required_fields(plan):
        if is_missing_value(resolve_path(record, field)):
            errors.append(f"required field missing: {field}")

    provenance = plan.get("provenance") or {}
    if isinstance(provenance, dict) and section_is_blocking(plan, "provenance"):
        provenance_field = str(provenance.get("field", "metadata.source_origin"))
        real_world_values = set(ensure_string_list(provenance.get("real_world_values")) or ["real_world"])
        reference_fields = ensure_string_list(provenance.get("reference_fields"))
        source_values = {value for value in values_for_field(record, provenance_field) if value != "__missing__"}
        if source_values & real_world_values and reference_fields:
            has_reference = any(not is_missing_value(resolve_path(record, field)) for field in reference_fields)
            if not has_reference:
                errors.append(
                    "real-world record is missing traceable provenance reference fields: "
                    + ", ".join(reference_fields)
                )

    return sorted(set(errors))


def load_review_map(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    reviews = {}
    for row in load_records(path):
        record_id = row.get("id")
        if not record_id:
            continue
        reviews[str(record_id)] = dict(row)
    return reviews


def load_records_for_verification(
    args: argparse.Namespace,
    connection,
    allow_injections: bool,
) -> list[dict[str, Any]]:
    if args.input:
        return [
            normalize_record(
                item,
                default_task_type="sft",
                source_type=args.source_type,
                allow_injections=allow_injections,
            )
            for item in load_records(args.input)
        ]

    statuses = tuple(args.from_status or ["raw_generated", "augmented", "seeded"])
    rows = fetch_records_by_status(connection, statuses)
    if args.source_run_id:
        rows = [row for row in rows if row["run_id"] == args.source_run_id]
    return [row_to_record(dict(row)) for row in rows[: args.limit]]


def apply_review(record: dict[str, Any], review: dict[str, Any] | None, plan: dict[str, Any] | None = None) -> tuple[str, str, int | None, str | None]:
    if not review:
        return "judge_pending", "pending", None, None

    plan = plan or {}
    status = str(review.get("status", "")).strip().lower()
    score = review.get("score")
    reason = review.get("reason")
    int_score = int(str(score)) if score not in (None, "") else None

    safety_notes = review.get("safety_notes")
    if safety_notes:
        record["judge_safety_notes"] = str(safety_notes)

    capability_delta_score = review.get("capability_delta_score")
    if capability_delta_score is not None:
        record["judge_capability_delta"] = capability_delta_score

    for flag in ("structural_pass", "instruction_following_pass", "grounding_pass", "format_pass"):
        if flag in review and not bool(review.get(flag)):
            return "verified_fail", "fail", int_score, str(reason or f"review flag failed: {flag}")

    unsupported_claims = review.get("unsupported_claims") or []
    if unsupported_claims:
        return "verified_fail", "fail", int_score, str(reason or "unsupported claims present")

    capability_delta = review.get("capability_delta_score")
    min_delta = review.get("min_capability_delta_score")
    if capability_delta not in (None, "") and min_delta not in (None, ""):
        try:
            if int(str(capability_delta)) < int(str(min_delta)):
                return "verified_fail", "fail", int_score, str(reason or "capability delta below review minimum")
        except ValueError:
            return "verified_fail", "fail", int_score, str(reason or "invalid capability_delta_score")

    review_requirements = plan.get("review_requirements") or {}
    min_cap_delta = review_requirements.get("min_capability_delta_score")
    if min_cap_delta not in (None, "") and capability_delta_score is not None:
        try:
            if int(str(capability_delta_score)) < int(str(min_cap_delta)):
                return "verified_fail", "fail", int_score, "capability_delta_score below minimum"
        except ValueError:
            pass

    require_grounding = review_requirements.get("require_grounding_pass")
    if require_grounding:
        grounding_val = review.get("grounding_pass")
        if grounding_val is False or grounding_val is None:
            return "verified_fail", "fail", int_score, "grounding_pass required but not present or failed"

    if status == "pass":
        return "verified_pass", "pass", int_score, str(reason or "")
    return "verified_fail", "fail", int_score, str(reason or "")


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    db_path = initialize_database(args.db) if args.db else initialize_database()
    run_id = args.run_id or f"run_{uuid.uuid4().hex[:12]}"
    review_map = load_review_map(args.review_file)
    evidence_map = load_evidence_map(args.evidence_file)
    allow_injections = resolve_allow_injections(
        args.allow_injections,
        args.user_query,
        args.source_type,
    )

    connection = get_connection(db_path)
    try:
        upsert_run(
            connection,
            run_id=run_id,
            user_query=args.user_query,
            mode="verify",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="in_progress",
        )

        records = load_records_for_verification(args, connection, allow_injections)
        summary: dict[str, Any] = {
            "run_id": run_id,
            "db_path": str(db_path),
            "allow_injections": allow_injections,
            "verified_pass": 0,
            "verified_fail": 0,
            "judge_pending": 0,
            "records_processed": 0,
            "details": [],
        }

        for record in records:
            errors = heuristic_errors(record, args, plan, evidence_map)
            result: dict[str, Any] = {
                "id": record["id"],
                "heuristic_errors": errors,
            }
            if errors:
                record["status"] = "verified_fail"
                record["pipeline_status"] = "fail"
                record["error_message"] = "; ".join(errors)
                summary["verified_fail"] += 1
            else:
                status, pipeline_status, score, reason = apply_review(
                    record,
                    review_map.get(record["id"]),
                    plan,
                )
                record["status"] = status
                record["pipeline_status"] = pipeline_status
                record["judge_score"] = score
                record["judge_reason"] = reason
                record["error_message"] = None

                if status == "verified_pass":
                    summary["verified_pass"] += 1
                elif status == "verified_fail":
                    summary["verified_fail"] += 1
                else:
                    summary["judge_pending"] += 1

                result["review"] = {
                    "status": status,
                    "score": score,
                    "reason": reason,
                }

            if args.input:
                record["run_id"] = run_id
                record["source_type"] = args.source_type

            upsert_record(connection, record)
            summary["records_processed"] += 1
            summary["details"].append(result)

        upsert_run(
            connection,
            run_id=run_id,
            user_query=args.user_query,
            mode="verify",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="completed",
        )
        connection.commit()
    finally:
        connection.close()

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
