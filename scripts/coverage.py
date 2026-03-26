from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import normalize_record, record_text, row_to_record
from scripts.utils.db import fetch_records_by_status, get_connection, initialize_database
from scripts.utils.files import load_records, write_json
from scripts.utils.similarity import find_duplicates

DEFAULT_GROUP_FIELDS = [
    "task_type",
    "metadata.topic",
    "metadata.subtopic",
    "metadata.intent",
    "metadata.response_shape",
    "metadata.instruction_fidelity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report effective-count, duplicate pressure, and coverage gaps while a dataset is still being generated."
    )
    parser.add_argument("--input", help="Optional JSON, JSONL, or CSV file to analyze directly.")
    parser.add_argument(
        "--from-status",
        action="append",
        default=[],
        help="Statuses to analyze from SQLite when --input is not used. Repeatable.",
    )
    parser.add_argument("--source-run-id", help="Filter analysis to a specific source run id.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum number of records to analyze from SQLite mode.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold used to estimate effective post-dedup count.",
    )
    parser.add_argument(
        "--group-by",
        action="append",
        default=[],
        help="Field path to summarize on the effective corpus. Repeatable, e.g. metadata.subtopic.",
    )
    parser.add_argument(
        "--plan-file",
        help=(
            "Optional JSON plan with target_effective_count, max_share_per_group, and "
            "group_minimums keyed by field path."
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def load_plan(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Coverage plan must be a JSON object")
    return payload


def load_analysis_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input:
        return [
            normalize_record(
                item,
                default_task_type="sft",
                source_type=str(item.get("source_type", "raw_dataset")),
                allow_injections=True,
            )
            for item in load_records(args.input)
        ]

    db_path = initialize_database(args.db) if args.db else initialize_database()
    connection = get_connection(db_path)
    try:
        statuses = tuple(args.from_status or ["raw_generated", "augmented", "judge_pending", "verified_pass"])
        rows = fetch_records_by_status(connection, statuses)
        if args.source_run_id:
            rows = [row for row in rows if row["run_id"] == args.source_run_id]
        rows = rows[: args.limit]
        return [row_to_record(dict(row)) for row in rows]
    finally:
        connection.close()


def resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def values_for_field(payload: dict[str, Any], field_path: str) -> list[str]:
    value = resolve_path(payload, field_path)
    if value in (None, "", []):
        return ["__missing__"]
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or ["__missing__"]
    return [str(value)]


def counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def count_groups(records: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for field in fields:
        counter: Counter[str] = Counter()
        for record in records:
            for value in values_for_field(record, field):
                counter[value] += 1
        counts[field] = counter_to_dict(counter)
    return counts


def compute_underrepresented(
    group_counts: dict[str, dict[str, int]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    group_minimums = plan.get("group_minimums") or {}
    if not isinstance(group_minimums, dict):
        return findings

    for field, expected in group_minimums.items():
        if not isinstance(expected, dict):
            continue
        actual = group_counts.get(str(field), {})
        for value, minimum in expected.items():
            actual_count = int(actual.get(str(value), 0))
            minimum_count = int(minimum)
            if actual_count >= minimum_count:
                continue
            findings.append(
                {
                    "field": str(field),
                    "value": str(value),
                    "count": actual_count,
                    "minimum": minimum_count,
                    "gap": minimum_count - actual_count,
                }
            )
    return sorted(findings, key=lambda item: (-int(item["gap"]), item["field"], item["value"]))


def compute_mode_collapse(
    group_counts: dict[str, dict[str, int]],
    total_records: int,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    max_share = plan.get("max_share_per_group")
    if max_share in (None, "") or total_records <= 0:
        return []

    findings: list[dict[str, Any]] = []
    max_share_value = float(max_share)
    for field, counts in group_counts.items():
        for value, count in counts.items():
            if value == "__missing__":
                continue
            share = count / total_records
            if share <= max_share_value:
                continue
            findings.append(
                {
                    "field": field,
                    "value": value,
                    "count": count,
                    "share": round(share, 4),
                    "max_share": max_share_value,
                }
            )
    return sorted(findings, key=lambda item: (-float(item["share"]), item["field"], item["value"]))


def compute_missing_metadata(
    group_counts: dict[str, dict[str, int]],
    total_records: int,
) -> list[dict[str, Any]]:
    if total_records <= 0:
        return []
    findings: list[dict[str, Any]] = []
    for field, counts in group_counts.items():
        missing_count = int(counts.get("__missing__", 0))
        if missing_count == 0:
            continue
        findings.append(
            {
                "field": field,
                "count": missing_count,
                "share": round(missing_count / total_records, 4),
            }
        )
    return sorted(findings, key=lambda item: (-float(item["share"]), item["field"]))


def build_recommendations(
    *,
    target_gap: int | None,
    underrepresented: list[dict[str, Any]],
    mode_collapse: list[dict[str, Any]],
) -> list[str]:
    recommendations: list[str] = []
    if target_gap and target_gap > 0:
        recommendations.append(
            f"Generate at least {target_gap} more unique records before considering the corpus complete."
        )
    for item in underrepresented[:10]:
        recommendations.append(
            f"Target {item['field']}={item['value']} for {item['gap']} additional effective records."
        )
    for item in mode_collapse[:5]:
        recommendations.append(
            f"Pause {item['field']}={item['value']} until its share drops below {item['max_share']:.2f}."
        )
    return recommendations


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    records = load_analysis_records(args)
    kept_ids, duplicate_details = find_duplicates(
        records,
        threshold=args.threshold,
        text_fn=record_text,
    )
    kept_lookup = {record["id"]: record for record in records}
    effective_records = [kept_lookup[record_id] for record_id in kept_ids if record_id in kept_lookup]

    group_fields = args.group_by or list((plan.get("group_minimums") or {}).keys()) or DEFAULT_GROUP_FIELDS
    group_counts = count_groups(effective_records, group_fields)
    underrepresented = compute_underrepresented(group_counts, plan)
    mode_collapse = compute_mode_collapse(group_counts, len(effective_records), plan)
    missing_metadata = compute_missing_metadata(group_counts, len(effective_records))

    target_effective_count = plan.get("target_effective_count")
    target_gap = None
    if target_effective_count not in (None, ""):
        target_gap = max(int(target_effective_count) - len(effective_records), 0)

    summary: dict[str, Any] = {
        "records_examined": len(records),
        "effective_count": len(effective_records),
        "duplicate_count": len(duplicate_details),
        "duplicate_rate": round((len(duplicate_details) / len(records)), 4) if records else 0.0,
        "threshold": args.threshold,
        "group_counts": group_counts,
        "coverage_gaps": underrepresented,
        "mode_collapse": mode_collapse,
        "missing_metadata": missing_metadata,
        "target_effective_count": (
            int(target_effective_count) if target_effective_count not in (None, "") else None
        ),
        "target_effective_gap": target_gap,
        "recommended_next_focus": build_recommendations(
            target_gap=target_gap,
            underrepresented=underrepresented,
            mode_collapse=mode_collapse,
        ),
        "duplicates": duplicate_details[:50],
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
