from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import record_text, row_to_record
from scripts.utils.db import (
    fetch_records_by_status,
    get_connection,
    initialize_database,
    upsert_record,
    upsert_run,
)
from scripts.utils.files import write_json
from scripts.utils.similarity import find_duplicates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate verified records in SQLite state.")
    parser.add_argument(
        "--from-status",
        action="append",
        default=[],
        help="Statuses to deduplicate from SQLite. Repeatable.",
    )
    parser.add_argument("--source-run-id", help="Filter deduplication to a specific run id.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold for near-duplicate detection.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of records to examine.",
    )
    parser.add_argument("--run-id", help="Optional run identifier. Defaults to a generated UUID.")
    parser.add_argument(
        "--user-query",
        default="dataset dedup",
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
        help="Source type metadata for the dedup run record.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = initialize_database(args.db) if args.db else initialize_database()
    run_id = args.run_id or f"run_{uuid.uuid4().hex[:12]}"

    connection = get_connection(db_path)
    try:
        upsert_run(
            connection,
            run_id=run_id,
            user_query=args.user_query,
            mode="dedup",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="in_progress",
        )

        statuses = tuple(args.from_status or ["verified_pass"])
        rows = fetch_records_by_status(connection, statuses)
        if args.source_run_id:
            rows = [row for row in rows if row["run_id"] == args.source_run_id]
        rows = rows[: args.limit]
        records = [row_to_record(dict(row)) for row in rows]

        kept_ids, duplicate_details = find_duplicates(
            records,
            threshold=args.threshold,
            text_fn=record_text,
        )
        duplicate_ids = {item["duplicate_id"] for item in duplicate_details}

        for record in records:
            if record["id"] not in duplicate_ids:
                continue
            detail = next(item for item in duplicate_details if item["duplicate_id"] == record["id"])
            record["status"] = "deduped"
            record["pipeline_status"] = "fail"
            record["error_message"] = f"Duplicate of {detail['kept_id']} ({detail['reason']})"
            upsert_record(connection, record)

        upsert_run(
            connection,
            run_id=run_id,
            user_query=args.user_query,
            mode="dedup",
            source_type=args.source_type,
            tool_context=args.tool_context,
            status="completed",
        )
        connection.commit()
    finally:
        connection.close()

    summary = {
        "run_id": run_id,
        "db_path": str(db_path),
        "records_examined": len(records),
        "kept_count": len(kept_ids),
        "duplicate_count": len(duplicate_details),
        "duplicates": duplicate_details,
    }
    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
