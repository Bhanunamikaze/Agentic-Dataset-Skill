from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import build_record_id, normalize_record, row_to_record
from scripts.utils.security import resolve_allow_injections
from scripts.utils.db import (
    fetch_records_by_status,
    get_connection,
    initialize_database,
    upsert_record,
    upsert_run,
)
from scripts.utils.files import load_records, write_json
from scripts.utils.schema import validate_record

DEFAULT_PERSONAS = ["general", "expert", "skeptical-reviewer"]
DEFAULT_DIFFICULTIES = ["easy", "medium", "hard"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import augmented drafts or create deterministic metadata variants."
    )
    parser.add_argument("--input", help="Path to augmented draft records in JSON, JSONL, or CSV.")
    parser.add_argument(
        "--from-status",
        action="append",
        default=[],
        help="Source statuses to augment from when no --input file is provided. Repeatable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of source records to expand in metadata-variant mode.",
    )
    parser.add_argument(
        "--persona",
        action="append",
        default=[],
        help="Persona variant for metadata expansion. Repeatable.",
    )
    parser.add_argument(
        "--difficulty",
        action="append",
        default=[],
        help="Difficulty variant for metadata expansion. Repeatable.",
    )
    parser.add_argument(
        "--source-run-id",
        help="Existing run identifier to read from in metadata-variant mode.",
    )
    parser.add_argument("--run-id", help="Optional run identifier. Defaults to a generated UUID.")
    parser.add_argument(
        "--user-query",
        default="dataset augment",
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
        help="Source type metadata for augmented records.",
    )
    allow_group = parser.add_mutually_exclusive_group()
    allow_group.add_argument(
        "--allow-injections",
        dest="allow_injections",
        action="store_true",
        help="Allow prompt-injection and jailbreak-like strings during import for intentional adversarial-security datasets.",
    )
    allow_group.add_argument(
        "--enforce-security-flags",
        dest="allow_injections",
        action="store_false",
        help="Keep prompt-injection flagging enabled, even for security or jailbreak dataset requests.",
    )
    parser.set_defaults(allow_injections=None)
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def load_input_records(args: argparse.Namespace, allow_injections: bool) -> list[dict[str, Any]]:
    raw_records = load_records(args.input)
    return [
        normalize_record(
            item,
            default_task_type="sft",
            source_type=args.source_type,
            allow_injections=allow_injections,
        )
        for item in raw_records
    ]


def build_variants(args: argparse.Namespace, connection) -> list[dict[str, Any]]:
    statuses = tuple(args.from_status or ["raw_generated"])
    personas = args.persona or DEFAULT_PERSONAS
    difficulties = args.difficulty or DEFAULT_DIFFICULTIES

    rows = fetch_records_by_status(connection, statuses)
    if args.source_run_id:
        rows = [row for row in rows if row["run_id"] == args.source_run_id]
    rows = rows[: args.limit]

    variants: list[dict[str, Any]] = []
    for row in rows:
        base_record = row_to_record(dict(row))
        for persona in personas:
            for difficulty in difficulties:
                if (
                    base_record["metadata"].get("persona") == persona
                    and base_record["metadata"].get("difficulty") == difficulty
                ):
                    continue

                variant = {
                    **base_record,
                    "id": "",
                    "metadata": {
                        **base_record["metadata"],
                        "persona": persona,
                        "difficulty": difficulty,
                        "augmentation_mode": "metadata_variant",
                        "parent_id": base_record["id"],
                        "rewrite_required": True,
                    },
                    "status": "augmented",
                    "pipeline_status": "rewrite",
                    "source_type": args.source_type,
                }
                variant["id"] = build_record_id(
                    {
                        "parent_id": base_record["id"],
                        "persona": persona,
                        "difficulty": difficulty,
                        "response": variant["response"],
                        "instruction": variant["instruction"],
                    }
                )
                variants.append(variant)
    return variants


def main() -> None:
    args = parse_args()
    db_path = initialize_database(args.db) if args.db else initialize_database()
    run_id = args.run_id or f"run_{uuid.uuid4().hex[:12]}"
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
            mode="augment",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="in_progress",
        )

        records = (
            load_input_records(args, allow_injections)
            if args.input
            else build_variants(args, connection)
        )
        summary: dict[str, Any] = {
            "run_id": run_id,
            "db_path": str(db_path),
            "allow_injections": allow_injections,
            "augmented": 0,
            "failed": 0,
            "record_ids": [],
            "errors": [],
        }

        for record in records:
            record["run_id"] = run_id
            record["source_type"] = args.source_type
            record["status"] = "augmented"
            errors = validate_record(record)
            if errors:
                summary["failed"] += 1
                summary["errors"].append({"id": record.get("id"), "errors": errors})
                continue

            upsert_record(connection, record)
            summary["augmented"] += 1
            summary["record_ids"].append(record["id"])

        upsert_run(
            connection,
            run_id=run_id,
            user_query=args.user_query,
            mode="augment",
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
