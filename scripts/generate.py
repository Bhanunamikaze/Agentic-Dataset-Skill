from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import build_seed_record, normalize_record
from scripts.utils.db import (
    get_connection,
    initialize_database,
    upsert_record,
    upsert_run,
)
from scripts.utils.files import load_records, write_json
from scripts.utils.schema import validate_record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load canonical dataset drafts or deterministic seeds into the SQLite run state. This script does not call external LLM APIs."
    )
    parser.add_argument("--input", help="Path to a JSON, JSONL, or CSV file of draft records.")
    parser.add_argument("--topic", help="Topic used to create deterministic seed placeholder rows.")
    parser.add_argument(
        "--count",
        type=int,
        default=500,
        help="Number of placeholder seed rows to create when --topic is used. Default: 500.",
    )
    parser.add_argument(
        "--task-type",
        choices=("auto", "sft", "dpo"),
        default="auto",
        help="Default task type when the input file does not specify one.",
    )
    parser.add_argument(
        "--source-type",
        default="generated",
        help="Source type metadata for created/imported records.",
    )
    parser.add_argument(
        "--allow-injections",
        action="store_true",
        help="Allow prompt-injection and jailbreak-like strings during import for intentional adversarial-security datasets.",
    )
    parser.add_argument("--run-id", help="Optional run identifier. Defaults to a generated UUID.")
    parser.add_argument(
        "--user-query",
        help="Original user request or run description. Defaults to the topic or input path.",
    )
    parser.add_argument(
        "--tool-context",
        default="generic",
        help="Originating tool context, for example codex, claude, or antigravity.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument(
        "--report",
        help="Optional path to write a JSON summary report.",
    )
    return parser.parse_args()


def infer_status(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        chosen = str(response.get("chosen", ""))
        rejected = str(response.get("rejected", ""))
        if chosen.startswith("[PENDING_") or rejected.startswith("[PENDING_"):
            return "seeded"
    else:
        text = str(response.get("text", ""))
        if text.startswith("[PENDING_"):
            return "seeded"
    return "raw_generated"


def load_or_seed_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input:
        raw_records = load_records(args.input)
        default_task_type = "sft" if args.task_type == "auto" else args.task_type
        return [
            normalize_record(
                item,
                default_task_type=default_task_type,
                source_type=args.source_type,
                allow_injections=args.allow_injections,
            )
            for item in raw_records
        ]

    if args.topic and args.count > 0:
        task_type = "sft" if args.task_type == "auto" else args.task_type
        return [
            asdict(
                build_seed_record(
                    topic=args.topic,
                    index=index,
                    task_type=task_type,
                    source_type=args.source_type,
                )
            )
            for index in range(1, args.count + 1)
        ]

    raise SystemExit("Provide --input or use --topic with a positive --count to create seed rows.")


def main() -> None:
    args = parse_args()
    db_path = initialize_database(args.db) if args.db else initialize_database()
    run_id = args.run_id or f"run_{uuid.uuid4().hex[:12]}"
    user_query = args.user_query or args.topic or args.input or "dataset generate"

    records = load_or_seed_records(args)
    summary: dict[str, Any] = {
        "run_id": run_id,
        "db_path": str(db_path),
        "source_type": args.source_type,
        "allow_injections": args.allow_injections,
        "imported": 0,
        "failed": 0,
        "record_ids": [],
        "errors": [],
    }

    connection = get_connection(db_path)
    try:
        upsert_run(
            connection,
            run_id=run_id,
            user_query=user_query,
            mode="generate",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="in_progress",
        )

        for record in records:
            record["run_id"] = run_id
            record["source_type"] = args.source_type
            record_status = str(record.get("status") or "").strip()
            if not record_status or record_status == "pending":
                record["status"] = infer_status(record)
            else:
                record["status"] = record_status

            errors = validate_record(record)
            if errors:
                summary["failed"] += 1
                summary["errors"].append({"id": record.get("id"), "errors": errors})
                continue

            upsert_record(connection, record)
            summary["imported"] += 1
            summary["record_ids"].append(record["id"])

        upsert_run(
            connection,
            run_id=run_id,
            user_query=user_query,
            mode="generate",
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
