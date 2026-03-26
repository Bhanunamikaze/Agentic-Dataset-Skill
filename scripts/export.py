from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import row_to_record
from scripts.utils.coverage_plan import load_plan
from scripts.utils.db import fetch_records_by_status, get_connection, initialize_database
from scripts.utils.files import write_csv, write_json, write_jsonl
from scripts.utils.schema import load_flat_export_schema
from scripts.utils.visibility import sanitize_records_for_model_visibility

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FLAT_SCHEMA = ROOT_DIR / "resources" / "target-schemas" / "csv_columns.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export verified dataset records into JSONL and CSV targets."
    )
    parser.add_argument(
        "--format",
        choices=("openai", "huggingface", "csv", "jsonl", "all"),
        default="openai",
        help="Export target format.",
    )
    parser.add_argument(
        "--from-status",
        action="append",
        default=[],
        help="Statuses to export from SQLite. Repeatable.",
    )
    parser.add_argument("--source-run-id", help="Filter export to a specific run id.")
    parser.add_argument(
        "--split",
        type=float,
        default=0.1,
        help="Holdout fraction for the test split. Default: 0.1",
    )
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed for dataset splitting.")
    parser.add_argument(
        "--output-dir",
        default="workspace",
        help="Directory for exported files and generated data card.",
    )
    parser.add_argument(
        "--schema-file",
        help="Optional flat target schema file for csv/jsonl exports.",
    )
    parser.add_argument(
        "--plan-file",
        help="Optional coverage/quality plan used for model-visibility redaction during export.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def get_cluster_key(record: dict[str, Any]) -> str:
    # Try explicit metadata keys often used for scenarios/topics
    meta = record.get("metadata", {})
    for key in ("scenario", "topic", "intent", "subtopic", "fingerprint"):
        if key in meta and meta[key]:
            return str(meta[key])
    # Fallback: Hash the first few words of the instruction to cluster similar templates
    import re
    instr = record.get("instruction", "")
    words = re.findall(r'\w+', instr.lower())[:6]
    return "_".join(words)

def split_records(
    records: list[dict[str, Any]],
    split_ratio: float,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if split_ratio <= 0.0 or len(records) < 2:
        return list(records), []

    # Group records by cluster key
    from collections import defaultdict
    clusters = defaultdict(list)
    for r in records:
        clusters[get_cluster_key(r)].append(r)

    # Shuffle the cluster keys
    cluster_keys = list(clusters.keys())
    random.Random(seed).shuffle(cluster_keys)

    train_records: list[dict[str, Any]] = []
    test_records: list[dict[str, Any]] = []
    
    target_test_count = int(float(len(records)) * split_ratio)
    if target_test_count == 0:
        target_test_count = 1

    # Greedily assign clusters to test until we hit the target
    for key in cluster_keys:
        if len(test_records) < target_test_count and len(test_records) + len(clusters[key]) <= target_test_count * 1.5:
            test_records.extend(clusters[key])
        elif len(test_records) == 0 and len(clusters[key]) >= target_test_count:
            test_records.extend(clusters[key])
        else:
            train_records.extend(clusters[key])
            
    if not test_records and cluster_keys:
        test_records.extend(clusters[cluster_keys[0]])
        train_records = []
        for k in cluster_keys[1:]:
            train_records.extend(clusters[k])

    random.Random(seed).shuffle(train_records)
    random.Random(seed).shuffle(test_records)

    return train_records, test_records


def to_openai_record(record: dict[str, Any]) -> dict[str, Any]:
    response = record["response"]
    if response["format"] == "single":
        messages = []
        if record["context"]:
            messages.append({"role": "system", "content": record["context"]})
        messages.append({"role": "user", "content": record["instruction"]})
        messages.append({"role": "assistant", "content": response["text"]})
        return {"messages": messages, "metadata": record["metadata"]}

    return {
        "input": {
            "instruction": record["instruction"],
            "context": record["context"],
        },
        "chosen": response["chosen"],
        "rejected": response["rejected"],
        "metadata": record["metadata"],
    }


def to_huggingface_record(record: dict[str, Any]) -> dict[str, Any]:
    response = record["response"]
    if response["format"] == "single":
        messages = []
        if record["context"]:
            messages.append({"role": "system", "content": record["context"]})
        messages.append({"role": "user", "content": record["instruction"]})
        messages.append({"role": "assistant", "content": response["text"]})
        return {
            "messages": messages,
            "metadata": record["metadata"],
        }
    return {
        "prompt": record["instruction"],
        "context": record["context"],
        "chosen": response["chosen"],
        "rejected": response["rejected"],
        "metadata": record["metadata"],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_source(record: dict[str, Any], source: str) -> Any:
    current: Any = record
    for part in source.split("."):
        if isinstance(current, dict):
            current = current.get(part, "")
        else:
            return ""
    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=True)
    return current


def to_flat_row(record: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    return {
        column["name"]: resolve_source(record, column["source"])
        for column in schema["columns"]
    }


def counter_dict(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def summarize_records(
    records: list[dict[str, Any]],
    *,
    train_count: int,
    test_count: int,
    export_format: str,
    schema_file: str | None,
    flat_schema: dict[str, Any],
    output_files: list[str],
    visibility_summary: dict[str, Any],
) -> dict[str, Any]:
    judge_values = [record["judge_score"] for record in records if record.get("judge_score") is not None]
    summary = {
        "generated_at": utc_now(),
        "records_exported": len(records),
        "train_count": train_count,
        "test_count": test_count,
        "format": export_format,
        "schema_file": schema_file or str(DEFAULT_FLAT_SCHEMA),
        "schema_name": flat_schema["name"],
        "flat_columns": [column["name"] for column in flat_schema["columns"]],
        "task_type_distribution": counter_dict([record["task_type"] for record in records]),
        "source_type_distribution": counter_dict(
            [str(record.get("source_type", "unknown")) for record in records]
        ),
        "difficulty_distribution": counter_dict(
            [str(record["metadata"].get("difficulty", "unknown")) for record in records]
        ),
        "persona_distribution": counter_dict(
            [str(record["metadata"].get("persona", "unknown")) for record in records]
        ),
        "judge_score_distribution": dict(sorted(Counter(judge_values).items())),
        "model_visibility": visibility_summary,
        "files": output_files,
    }
    return summary


def write_data_card(
    path: Path,
    summary: dict[str, Any],
) -> Path:
    def dict_lines(payload: dict[str, Any]) -> list[str]:
        if not payload:
            return ["- none"]
        return [f"- {key}: {value}" for key, value in payload.items()]

    lines = [
        "# Dataset Card",
        "",
        "## Summary",
        f"- Generated at: {summary['generated_at']}",
        f"- Total exported records: {summary['records_exported']}",
        f"- Train count: {summary['train_count']}",
        f"- Test count: {summary['test_count']}",
        f"- Export format: {summary['format']}",
        f"- Flat schema file: {summary['schema_file']}",
        f"- Flat schema name: {summary['schema_name']}",
        "",
        "## Flat Columns",
        *[f"- {column}" for column in summary["flat_columns"]],
        "",
        "## Distributions",
        "### Task Types",
        *dict_lines(summary["task_type_distribution"]),
        "",
        "### Source Types",
        *dict_lines(summary["source_type_distribution"]),
        "",
        "### Difficulty",
        *dict_lines(summary["difficulty_distribution"]),
        "",
        "### Persona",
        *dict_lines(summary["persona_distribution"]),
        "",
        "### Judge Scores",
        *dict_lines(summary["judge_score_distribution"]),
        "",
        "## Artifacts",
        *[f"- {file_path}" for file_path in summary["files"]],
        "",
        "## Generation Method",
        "- Tool-native reasoning in Codex, Antigravity, or Claude Code.",
        "- Deterministic local scripts for normalization, verification, deduplication, and export.",
        "",
        "## Known Limits",
        "- Review-file judgments are only present when an IDE-agent or user supplies them.",
        "- Web-derived datasets depend on the evidence collected during the run.",
        "",
        "## License",
        "- Set by the dataset author or downstream project requirements.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_jsonl_pair(
    output_dir: Path,
    prefix: str,
    train_records: list[dict[str, Any]],
    test_records: list[dict[str, Any]],
) -> list[str]:
    written: list[str] = []
    train_path = output_dir / f"{prefix}_train.jsonl"
    write_jsonl(train_path, train_records)
    written.append(str(train_path))
    if test_records:
        test_path = output_dir / f"{prefix}_test.jsonl"
        write_jsonl(test_path, test_records)
        written.append(str(test_path))
    return written


def export_csv_pair(
    output_dir: Path,
    prefix: str,
    train_records: list[dict[str, Any]],
    test_records: list[dict[str, Any]],
    *,
    fieldnames: list[str],
) -> list[str]:
    written: list[str] = []
    train_path = output_dir / f"{prefix}_train.csv"
    write_csv(train_path, train_records, fieldnames=fieldnames)
    written.append(str(train_path))
    if test_records:
        test_path = output_dir / f"{prefix}_test.csv"
        write_csv(test_path, test_records, fieldnames=fieldnames)
        written.append(str(test_path))
    return written


def export_flat_jsonl_pair(
    output_dir: Path,
    prefix: str,
    train_records: list[dict[str, Any]],
    test_records: list[dict[str, Any]],
) -> list[str]:
    written: list[str] = []
    train_path = output_dir / f"{prefix}_train.jsonl"
    write_jsonl(train_path, train_records)
    written.append(str(train_path))
    if test_records:
        test_path = output_dir / f"{prefix}_test.jsonl"
        write_jsonl(test_path, test_records)
        written.append(str(test_path))
    return written


def main() -> None:
    args = parse_args()
    if not 0 <= args.split <= 1:
        raise SystemExit("--split must be between 0 and 1 inclusive")
    plan = load_plan(args.plan_file)

    db_path = initialize_database(args.db) if args.db else initialize_database()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    connection = get_connection(db_path)
    try:
        statuses = tuple(args.from_status or ["verified_pass"])
        rows = fetch_records_by_status(connection, statuses)
        if args.source_run_id:
            rows = [row for row in rows if row["run_id"] == args.source_run_id]
        records = [row_to_record(dict(row)) for row in rows if row["pipeline_status"] == "pass"]
    finally:
        connection.close()

    train_records, test_records = split_records(records, args.split, args.seed)
    train_records, train_visibility = sanitize_records_for_model_visibility(train_records, plan)
    test_records, test_visibility = sanitize_records_for_model_visibility(test_records, plan)
    visibility_summary = {
        "enabled": bool(train_visibility.get("enabled") or test_visibility.get("enabled")),
        "instruction_modified": int(train_visibility.get("instruction_modified", 0))
        + int(test_visibility.get("instruction_modified", 0)),
        "context_modified": int(train_visibility.get("context_modified", 0))
        + int(test_visibility.get("context_modified", 0)),
        "records_modified": int(train_visibility.get("records_modified", 0))
        + int(test_visibility.get("records_modified", 0)),
    }
    written_files: list[str] = []
    flat_schema_path = Path(args.schema_file) if args.schema_file else DEFAULT_FLAT_SCHEMA
    flat_schema = load_flat_export_schema(flat_schema_path)
    flat_train = [to_flat_row(record, flat_schema) for record in train_records]
    flat_test = [to_flat_row(record, flat_schema) for record in test_records]
    flat_fieldnames = [column["name"] for column in flat_schema["columns"]]

    if args.format in ("openai", "all"):
        written_files.extend(
            export_jsonl_pair(
                output_dir,
                "openai",
                [to_openai_record(record) for record in train_records],
                [to_openai_record(record) for record in test_records],
            )
        )

    if args.format in ("huggingface", "all"):
        written_files.extend(
            export_jsonl_pair(
                output_dir,
                "huggingface",
                [to_huggingface_record(record) for record in train_records],
                [to_huggingface_record(record) for record in test_records],
            )
        )

    if args.format in ("csv", "all"):
        written_files.extend(
            export_csv_pair(
                output_dir,
                "dataset",
                flat_train,
                flat_test,
                fieldnames=flat_fieldnames,
            )
        )

    if args.format in ("jsonl", "all"):
        written_files.extend(
            export_flat_jsonl_pair(
                output_dir,
                "flat",
                flat_train,
                flat_test,
            )
        )

    # Phase 6E: Always dump the raw canonical artifacts alongside target schemas
    written_files.extend(
        export_flat_jsonl_pair(
            output_dir,
            "canonical",
            train_records,
            test_records,
        )
    )

    summary = summarize_records(
        records,
        train_count=len(train_records),
        test_count=len(test_records),
        export_format=args.format,
        schema_file=str(flat_schema_path),
        flat_schema=flat_schema,
        output_files=written_files,
        visibility_summary=visibility_summary,
    )
    data_card_path = write_data_card(output_dir / "DATA_CARD.md", summary)
    summary["files"] = written_files + [str(data_card_path)]
    summary["db_path"] = str(db_path)
    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
