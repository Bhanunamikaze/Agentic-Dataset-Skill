from __future__ import annotations

import argparse
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


def heuristic_errors(record: dict[str, Any], args: argparse.Namespace, plan: dict[str, Any] | None = None) -> list[str]:
    errors = validate_record(record)

    instruction = str(record.get("instruction", "")).strip()
    metadata = dict(record.get("metadata") or {})
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
        for pattern in REFUSAL_PATTERNS:
            if pattern.search(stripped):
                errors.append(f"response matched refusal pattern: {pattern.pattern}")
                break

    plan = plan or {}
    for field in plan_required_fields(plan):
        if is_missing_value(resolve_path(record, field)):
            errors.append(f"required field missing: {field}")

    provenance = plan.get("provenance") or {}
    if isinstance(provenance, dict):
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


def apply_review(record: dict[str, Any], review: dict[str, Any] | None) -> tuple[str, str, int | None, str | None]:
    if not review:
        return "judge_pending", "pending", None, None

    status = str(review.get("status", "")).strip().lower()
    score = review.get("score")
    reason = review.get("reason")
    if status == "pass":
        return "verified_pass", "pass", int(str(score)) if score not in (None, "") else None, str(reason or "")
    return "verified_fail", "fail", int(str(score)) if score not in (None, "") else None, str(reason or "")


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    db_path = initialize_database(args.db) if args.db else initialize_database()
    run_id = args.run_id or f"run_{uuid.uuid4().hex[:12]}"
    review_map = load_review_map(args.review_file)
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
            errors = heuristic_errors(record, args, plan)
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
