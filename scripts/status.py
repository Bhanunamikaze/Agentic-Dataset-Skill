from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coverage import (
    DEFAULT_GROUP_FIELDS,
    build_recommendations,
    compute_missing_metadata,
    compute_mode_collapse,
    compute_underrepresented,
    count_groups,
)
from scripts.utils.canonical import record_text, row_to_record
from scripts.utils.coverage_plan import load_plan, plan_required_fields
from scripts.utils.db import fetch_records_by_status, get_connection, initialize_database
from scripts.utils.files import write_json
from scripts.utils.similarity import find_duplicates

DEFAULT_STATUSES = ("verified_pass", "judge_pending", "raw_generated", "augmented")
DEFAULT_THRESHOLD = 0.85


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Single-shot corpus snapshot reporting effective count, coverage gaps, and fail reasons."
    )
    parser.add_argument(
        "--plan-file",
        help="Optional coverage/quality plan with target_effective_count and bucket gates.",
    )
    parser.add_argument(
        "--source-run-id",
        help="Filter snapshot to a specific source run id.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional path to the SQLite database. Defaults to workspace/run_state.sqlite.",
    )
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def parse_fail_reasons(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        if record.get("status") != "verified_fail":
            continue
        message = str(record.get("error_message") or "").strip()
        if not message:
            continue
        for chunk in message.split("; "):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Canonical prefix: text up to first ":" or "(" so similar errors cluster.
            prefix = chunk.split(":", 1)[0].split("(", 1)[0].strip().lower()
            if prefix:
                counter[prefix] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in counter.most_common(10)
    ]


def compute_effective_records(
    records: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    kept_ids, _ = find_duplicates(records, threshold=threshold, text_fn=record_text)
    kept_lookup = {record["id"]: record for record in records}
    return [kept_lookup[record_id] for record_id in kept_ids if record_id in kept_lookup]


def fetch_all_records(
    db_path: Path, source_run_id: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (all_examined, dedup_candidate_records) for the snapshot."""
    connection = get_connection(db_path)
    try:
        all_rows = list(
            connection.execute("SELECT * FROM records ORDER BY created_at ASC")
        )
        if source_run_id:
            all_rows = [row for row in all_rows if row["run_id"] == source_run_id]
        all_records = [row_to_record(dict(row)) for row in all_rows]
        dedup_records = [
            record for record in all_records if record.get("status") in DEFAULT_STATUSES
        ]
        return all_records, dedup_records
    finally:
        connection.close()


def compute_real_world_ratio(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    real_world = sum(
        1
        for record in records
        if str((record.get("metadata") or {}).get("source_origin") or "") == "real_world"
    )
    return round(real_world / len(records), 4)


def compute_evidence_linked_ratio(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    linked = 0
    for record in records:
        metadata = record.get("metadata") or {}
        value = metadata.get("evidence_ids") or metadata.get("evidence_id")
        if isinstance(value, str) and value.strip():
            linked += 1
        elif isinstance(value, list) and any(str(item).strip() for item in value):
            linked += 1
    return round(linked / len(records), 4)


def build_status_recommendations(
    *,
    target_gap: int | None,
    underrepresented: list[dict[str, Any]],
    real_world_ratio: float,
    minimum_real_world_share: float | None,
    base_recommendations: list[str],
) -> list[str]:
    actions: list[str] = []
    if target_gap and target_gap > 0:
        actions.append(f"Generate {target_gap} more records to reach target effective count.")
    for item in underrepresented[:3]:
        actions.append(
            f"Draft {item['gap']} records targeting {item['field']}={item['value']}."
        )
    if (
        minimum_real_world_share is not None
        and real_world_ratio < float(minimum_real_world_share)
    ):
        actions.append(
            "Raise real-world ratio via research before continuing synthetic drafting."
        )
    # Fall back to any other coverage recommendations the underlying helper emitted.
    for rec in base_recommendations:
        if len(actions) >= 5:
            break
        if rec in actions:
            continue
        actions.append(rec)
    return actions[:5]


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    db_path = initialize_database(args.db) if args.db else initialize_database()

    all_records, dedup_records = fetch_all_records(db_path, args.source_run_id)

    status_counter: Counter[str] = Counter()
    for record in all_records:
        status_counter[str(record.get("status") or "unknown")] += 1
    status_counts = dict(sorted(status_counter.items(), key=lambda item: (-item[1], item[0])))

    effective_records = compute_effective_records(dedup_records, DEFAULT_THRESHOLD)

    required_fields = plan_required_fields(plan)
    group_fields = list((plan.get("group_minimums") or {}).keys()) or list(DEFAULT_GROUP_FIELDS)
    if required_fields:
        group_fields = list(dict.fromkeys([*group_fields, *required_fields]))
    bucket_fills = count_groups(effective_records, group_fields)
    bucket_gaps = compute_underrepresented(bucket_fills, plan)
    mode_collapse_findings = compute_mode_collapse(
        bucket_fills, len(effective_records), plan
    )
    missing_required_fields = compute_missing_metadata(
        effective_records,
        len(effective_records),
        required_fields or list(DEFAULT_GROUP_FIELDS),
    )

    target_effective_count = plan.get("target_effective_count")
    target_gap: int | None = None
    if target_effective_count not in (None, ""):
        target_gap = max(int(target_effective_count) - len(effective_records), 0)

    real_world_ratio = compute_real_world_ratio(effective_records)
    evidence_linked_ratio = compute_evidence_linked_ratio(effective_records)
    fail_reasons_top = parse_fail_reasons(all_records)

    provenance = plan.get("provenance") or {}
    minimum_real_world_share = provenance.get("minimum_real_world_share")
    minimum_real_world_share_value = (
        float(minimum_real_world_share)
        if minimum_real_world_share not in (None, "")
        else None
    )

    base_recommendations = build_recommendations(
        target_gap=target_gap,
        underrepresented=bucket_gaps,
        mode_collapse=mode_collapse_findings,
        joint_coverage_gaps=[],
        joint_mode_collapse=[],
        provenance_findings=[],
        response_prefix_findings=[],
        response_length_findings=[],
        response_structure_findings=[],
    )

    recommended_next_focus = build_status_recommendations(
        target_gap=target_gap,
        underrepresented=bucket_gaps,
        real_world_ratio=real_world_ratio,
        minimum_real_world_share=minimum_real_world_share_value,
        base_recommendations=base_recommendations,
    )

    summary: dict[str, Any] = {
        "db_path": str(db_path),
        "records_examined": len(all_records),
        "effective_count": len(effective_records),
        "target_effective_count": (
            int(target_effective_count) if target_effective_count not in (None, "") else None
        ),
        "target_gap": target_gap,
        "status_counts": status_counts,
        "real_world_ratio": real_world_ratio,
        "evidence_linked_ratio": evidence_linked_ratio,
        "fail_reasons_top": fail_reasons_top,
        "bucket_fills": bucket_fills,
        "bucket_gaps": bucket_gaps,
        "mode_collapse_findings": mode_collapse_findings,
        "missing_required_fields": missing_required_fields,
        "recommended_next_focus": recommended_next_focus,
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
