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
from scripts.utils.coverage_plan import (
    bucket_keys_for_fields,
    ensure_string_list,
    is_missing_value,
    load_plan,
    plan_required_fields,
    resolve_path,
    values_for_field,
)
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
            "Optional JSON plan with target_effective_count, max_share_per_group, "
            "group_minimums, required_fields, provenance rules, joint_group_rules, "
            "and response_prefix limits."
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


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
    records: list[dict[str, Any]],
    total_records: int,
    fields: list[str],
) -> list[dict[str, Any]]:
    if total_records <= 0:
        return []
    findings: list[dict[str, Any]] = []
    for field in fields:
        missing_count = sum(1 for record in records if is_missing_value(resolve_path(record, field)))
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


def compute_joint_groups(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    counts_by_rule: dict[str, dict[str, int]] = {}
    coverage_gaps: list[dict[str, Any]] = []
    mode_collapse: list[dict[str, Any]] = []

    for raw_rule in plan.get("joint_group_rules") or []:
        if not isinstance(raw_rule, dict):
            continue
        fields = ensure_string_list(raw_rule.get("fields"))
        if len(fields) < 2:
            continue

        name = str(raw_rule.get("name") or " x ".join(fields))
        counter: Counter[str] = Counter()
        for record in records:
            for bucket in bucket_keys_for_fields(record, fields):
                counter[bucket] += 1
        counts_by_rule[name] = counter_to_dict(counter)

        minimums = raw_rule.get("minimums") or {}
        if isinstance(minimums, dict):
            for value, minimum in minimums.items():
                actual_count = int(counter.get(str(value), 0))
                minimum_count = int(minimum)
                if actual_count >= minimum_count:
                    continue
                coverage_gaps.append(
                    {
                        "name": name,
                        "fields": fields,
                        "value": str(value),
                        "count": actual_count,
                        "minimum": minimum_count,
                        "gap": minimum_count - actual_count,
                    }
                )

        max_share = raw_rule.get("max_share")
        if max_share in (None, "") or not records:
            continue
        max_share_value = float(max_share)
        for value, count in counter.items():
            if "__missing__" in value:
                continue
            share = count / len(records)
            if share <= max_share_value:
                continue
            mode_collapse.append(
                {
                    "name": name,
                    "fields": fields,
                    "value": value,
                    "count": count,
                    "share": round(share, 4),
                    "max_share": max_share_value,
                }
            )

    return (
        counts_by_rule,
        sorted(coverage_gaps, key=lambda item: (-int(item["gap"]), item["name"], item["value"])),
        sorted(mode_collapse, key=lambda item: (-float(item["share"]), item["name"], item["value"])),
    )


def primary_response_text(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return str(response.get("chosen") or response.get("rejected") or "")
    return str(response.get("text", ""))


def compute_response_prefix(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    config = plan.get("response_prefix") or {}
    if not isinstance(config, dict) or not config:
        return None, []
    if not records:
        return {
            "prefix_length": int(config.get("prefix_length", 48)),
            "max_share": float(config.get("max_share", 1.0)),
            "top_prefixes": [],
        }, []

    prefix_length = int(config.get("prefix_length", 48))
    max_share = config.get("max_share")
    sample_limit = int(config.get("sample_limit", 10))
    counter: Counter[str] = Counter()
    display_map: dict[str, str] = {}

    for record in records:
        normalized = " ".join(primary_response_text(record).strip().split())
        if not normalized:
            continue
        key = normalized.lower()[:prefix_length]
        counter[key] += 1
        display_map.setdefault(key, normalized[:prefix_length])

    top_prefixes = [
        {
            "prefix": display_map[key],
            "count": count,
            "share": round(count / len(records), 4),
        }
        for key, count in counter.most_common(sample_limit)
    ]
    findings: list[dict[str, Any]] = []
    if max_share not in (None, ""):
        max_share_value = float(max_share)
        for key, count in counter.items():
            share = count / len(records)
            if count <= 1 or share <= max_share_value:
                continue
            findings.append(
                {
                    "prefix": display_map[key],
                    "count": count,
                    "share": round(share, 4),
                    "max_share": max_share_value,
                }
            )
    findings.sort(key=lambda item: (-float(item["share"]), item["prefix"]))
    return {
        "prefix_length": prefix_length,
        "max_share": float(max_share) if max_share not in (None, "") else None,
        "top_prefixes": top_prefixes,
    }, findings


def compute_provenance(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    config = plan.get("provenance") or {}
    if not isinstance(config, dict) or not config:
        return None, []

    field = str(config.get("field", "metadata.source_origin"))
    real_world_values = set(ensure_string_list(config.get("real_world_values")) or ["real_world"])
    reference_fields = ensure_string_list(config.get("reference_fields"))
    counter: Counter[str] = Counter()
    real_world_count = 0
    traceable_real_world_count = 0
    untraceable_real_world_count = 0

    for record in records:
        values = values_for_field(record, field)
        for value in values:
            counter[value] += 1
        value_set = {value for value in values if value != "__missing__"}
        if not (value_set & real_world_values):
            continue
        real_world_count += 1
        has_reference = any(not is_missing_value(resolve_path(record, path)) for path in reference_fields)
        if has_reference:
            traceable_real_world_count += 1
        else:
            untraceable_real_world_count += 1

    total_records = len(records)
    real_world_share = (real_world_count / total_records) if total_records else 0.0
    findings: list[dict[str, Any]] = []
    minimum_real_world_share = config.get("minimum_real_world_share")
    if minimum_real_world_share not in (None, "") and total_records:
        minimum_share = float(minimum_real_world_share)
        if real_world_share < minimum_share:
            findings.append(
                {
                    "type": "real_world_share",
                    "field": field,
                    "count": real_world_count,
                    "share": round(real_world_share, 4),
                    "minimum_share": minimum_share,
                }
            )
    if reference_fields and untraceable_real_world_count > 0 and real_world_count > 0:
        findings.append(
            {
                "type": "real_world_traceability",
                "field": field,
                "count": untraceable_real_world_count,
                "share": round(untraceable_real_world_count / real_world_count, 4),
                "reference_fields": reference_fields,
            }
        )

    return {
        "field": field,
        "counts": counter_to_dict(counter),
        "real_world_values": sorted(real_world_values),
        "real_world_count": real_world_count,
        "real_world_share": round(real_world_share, 4),
        "traceable_real_world_count": traceable_real_world_count,
        "untraceable_real_world_count": untraceable_real_world_count,
        "reference_fields": reference_fields,
        "minimum_real_world_share": (
            float(minimum_real_world_share) if minimum_real_world_share not in (None, "") else None
        ),
    }, findings


def build_recommendations(
    *,
    target_gap: int | None,
    underrepresented: list[dict[str, Any]],
    mode_collapse: list[dict[str, Any]],
    joint_coverage_gaps: list[dict[str, Any]],
    joint_mode_collapse: list[dict[str, Any]],
    provenance_findings: list[dict[str, Any]],
    response_prefix_findings: list[dict[str, Any]],
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
    for item in joint_coverage_gaps[:10]:
        recommendations.append(
            f"Target joint bucket {item['name']}={item['value']} for {item['gap']} additional effective records."
        )
    for item in joint_mode_collapse[:5]:
        recommendations.append(
            f"Pause joint bucket {item['name']}={item['value']} until its share drops below {item['max_share']:.2f}."
        )
    for item in provenance_findings:
        if item["type"] == "real_world_share":
            recommendations.append(
                f"Increase real-world grounded records until {item['field']} reaches {item['minimum_share']:.2f} share."
            )
        elif item["type"] == "real_world_traceability":
            recommendations.append(
                "Add source references to every real-world grounded record before treating the corpus as complete."
            )
    for item in response_prefix_findings[:5]:
        recommendations.append(
            f"Rewrite overused response openings like '{item['prefix']}' until they fall below {item['max_share']:.2f} share."
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
    required_fields = plan_required_fields(plan)
    if required_fields:
        group_fields = list(dict.fromkeys([*group_fields, *required_fields]))
    group_counts = count_groups(effective_records, group_fields)
    underrepresented = compute_underrepresented(group_counts, plan)
    mode_collapse = compute_mode_collapse(group_counts, len(effective_records), plan)
    missing_metadata = compute_missing_metadata(
        effective_records,
        len(effective_records),
        required_fields or group_fields,
    )
    joint_group_counts, joint_coverage_gaps, joint_mode_collapse = compute_joint_groups(
        effective_records,
        plan,
    )
    provenance_summary, provenance_findings = compute_provenance(effective_records, plan)
    response_prefix_summary, response_prefix_findings = compute_response_prefix(effective_records, plan)

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
        "required_fields": required_fields,
        "joint_group_counts": joint_group_counts,
        "joint_coverage_gaps": joint_coverage_gaps,
        "joint_mode_collapse": joint_mode_collapse,
        "provenance": provenance_summary,
        "provenance_findings": provenance_findings,
        "response_prefix": response_prefix_summary,
        "response_prefix_findings": response_prefix_findings,
        "target_effective_count": (
            int(target_effective_count) if target_effective_count not in (None, "") else None
        ),
        "target_effective_gap": target_gap,
        "recommended_next_focus": build_recommendations(
            target_gap=target_gap,
            underrepresented=underrepresented,
            mode_collapse=mode_collapse,
            joint_coverage_gaps=joint_coverage_gaps,
            joint_mode_collapse=joint_mode_collapse,
            provenance_findings=provenance_findings,
            response_prefix_findings=response_prefix_findings,
        ),
        "duplicates": duplicate_details[:50],
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
