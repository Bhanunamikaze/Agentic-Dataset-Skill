from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.db import get_connection, initialize_database

ROOT_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = str(ROOT_DIR / "workspace" / "record_history.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record a lineage snapshot of the current SQLite database state."
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to the SQLite database.",
    )
    parser.add_argument(
        "--output",
        default=_DEFAULT_OUTPUT,
        help="Output JSONL file (appended). Default: workspace/record_history.jsonl",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional free-text label for this snapshot.",
    )
    parser.add_argument(
        "--source-run-id",
        default=None,
        help="Optional run_id to associate with this snapshot.",
    )
    return parser.parse_args()


# Statuses tracked in status_counts
_TRACKED_STATUSES = (
    "raw_generated",
    "augmented",
    "verified_pass",
    "verified_fail",
    "judge_pending",
    "deduped",
)


def collect_status_counts(connection) -> dict[str, int]:
    """Count rows per status from the records table."""
    counts = {s: 0 for s in _TRACKED_STATUSES}
    rows = connection.execute(
        "SELECT status, COUNT(*) AS cnt FROM records GROUP BY status"
    ).fetchall()
    for row in rows:
        status = row["status"]
        if status in counts:
            counts[status] = row["cnt"]
    return counts


def collect_task_type_counts(connection) -> dict[str, int]:
    """
    Count rows by task_type parsed from the metadata_json column.
    Falls back gracefully if the column is absent or JSON is malformed.
    """
    # Check whether the column exists
    try:
        cols = {
            r["name"]
            for r in connection.execute("PRAGMA table_info(records)").fetchall()
        }
    except Exception:
        return {}

    if "metadata_json" not in cols:
        return {}

    try:
        rows = connection.execute(
            "SELECT metadata_json FROM records WHERE metadata_json IS NOT NULL"
        ).fetchall()
    except Exception:
        return {}

    counts: dict[str, int] = {}
    for row in rows:
        try:
            meta = json.loads(row["metadata_json"] or "{}")
            task_type = meta.get("task_type")
            if task_type:
                counts[task_type] = counts.get(task_type, 0) + 1
        except Exception:
            continue
    return counts


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()

    # Initialize schema if the DB is new; safe to call on existing DBs
    initialize_database(db_path)

    connection = get_connection(db_path)
    try:
        status_counts = collect_status_counts(connection)
        task_type_counts = collect_task_type_counts(connection)
    finally:
        connection.close()

    total_records = sum(status_counts.values())
    effective_count = status_counts.get("verified_pass", 0) + status_counts.get("judge_pending", 0)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "note": args.note or "",
        "source_run_id": args.source_run_id,
        "status_counts": status_counts,
        "total_records": total_records,
        "effective_count": effective_count,
        "task_type_counts": task_type_counts,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")

    print(json.dumps(record, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
