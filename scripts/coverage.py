from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from urllib.parse import urlparse
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
    "metadata.source_origin",
    "metadata.response_shape",
    "metadata.instruction_fidelity",
]

DEFAULT_REQUIRED_FIELDS = [
    "metadata.source_origin",
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
            "response_prefix limits, response_length limits, and response_structure limits."
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


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(max(int(round((len(ordered) - 1) * fraction)), 0), len(ordered) - 1)
    return int(ordered[index])


def compute_response_length(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    config = plan.get("response_length") or {}
    if not isinstance(config, dict) or not config:
        return None, []

    lengths = [len(primary_response_text(record).strip()) for record in records]
    if not lengths:
        return {
            "median_chars": 0,
            "p90_chars": 0,
            "max_chars": 0,
            "share_over_limit": 0.0,
            "over_limit": int(config.get("over_chars_limit", 0) or 0),
        }, []

    median_chars = int(statistics.median(lengths))
    p90_chars = percentile(lengths, 0.9)
    max_chars = max(lengths)
    over_limit = int(config.get("over_chars_limit", 0) or 0)
    over_limit_count = sum(1 for value in lengths if over_limit > 0 and value > over_limit)
    share_over_limit = (over_limit_count / len(lengths)) if over_limit > 0 else 0.0

    findings: list[dict[str, Any]] = []
    max_median_chars = config.get("max_median_chars")
    if max_median_chars not in (None, "") and median_chars > int(max_median_chars):
        findings.append(
            {
                "type": "median_chars",
                "median_chars": median_chars,
                "max_median_chars": int(max_median_chars),
            }
        )
    max_share_over_limit = config.get("max_share_over_limit")
    if (
        over_limit > 0
        and max_share_over_limit not in (None, "")
        and share_over_limit > float(max_share_over_limit)
    ):
        findings.append(
            {
                "type": "share_over_limit",
                "over_limit": over_limit,
                "share": round(share_over_limit, 4),
                "max_share": float(max_share_over_limit),
                "count": over_limit_count,
            }
        )

    return {
        "median_chars": median_chars,
        "p90_chars": p90_chars,
        "max_chars": max_chars,
        "share_over_limit": round(share_over_limit, 4),
        "over_limit": over_limit,
    }, findings


def structure_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": {key: structure_shape(item) for key, item in sorted(value.items())},
        }
    if isinstance(value, list):
        item_shapes = sorted(
            {json.dumps(structure_shape(item), sort_keys=True) for item in value}
        )
        return {"type": "array", "items": item_shapes}
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if value is None:
        return "null"
    return "string"


def structure_display(value: Any) -> str:
    if isinstance(value, dict):
        return "object(" + ",".join(sorted(value.keys())) + ")"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if value is None:
        return "null"
    return "string"


def response_structure_signature(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "empty", "empty"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return "plain_text", "plain_text"
        return json.dumps(structure_shape(payload), sort_keys=True), structure_display(payload)
    return "plain_text", "plain_text"


def compute_response_structure(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    config = plan.get("response_structure") or {}
    if not isinstance(config, dict) or not config:
        return None, []

    sample_limit = int(config.get("sample_limit", 10))
    max_share = config.get("max_share")
    counter: Counter[str] = Counter()
    display_map: dict[str, str] = {}
    for record in records:
        signature, display = response_structure_signature(primary_response_text(record))
        counter[signature] += 1
        display_map.setdefault(signature, display)

    top_structures = [
        {
            "signature": display_map[key],
            "count": count,
            "share": round(count / len(records), 4) if records else 0.0,
        }
        for key, count in counter.most_common(sample_limit)
    ]

    findings: list[dict[str, Any]] = []
    if max_share not in (None, "") and records:
        max_share_value = float(max_share)
        for signature, count in counter.items():
            share = count / len(records)
            if count <= 1 or share <= max_share_value:
                continue
            findings.append(
                {
                    "signature": display_map[signature],
                    "count": count,
                    "share": round(share, 4),
                    "max_share": max_share_value,
                }
            )
    findings.sort(key=lambda item: (-float(item["share"]), item["signature"]))
    return {
        "top_structures": top_structures,
        "max_share": float(max_share) if max_share not in (None, "") else None,
    }, findings


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




def source_domain_for_record(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") or {}
    if metadata.get("source_domain"):
        return str(metadata["source_domain"])
    uri = str(record.get("source_uri") or "")
    if uri.startswith(("http://", "https://")):
        return urlparse(uri).netloc.lower().removeprefix("www.") or "__missing__"
    if uri:
        return "local"
    return "__missing__"


def record_evidence_ids(record: dict[str, Any]) -> list[str]:
    metadata = record.get("metadata") or {}
    value = metadata.get("evidence_ids") or metadata.get("evidence_id") or []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def compute_research_coverage(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    config = plan.get("research") or {}
    if not isinstance(config, dict) or not config:
        return None, []
    total = len(records)
    domains = Counter(source_domain_for_record(record) for record in records)
    traceable = sum(1 for record in records if record.get("source_uri") or (record.get("metadata") or {}).get("reference_urls"))
    evidence_linked = sum(1 for record in records if record_evidence_ids(record))
    quality_values: list[float] = []
    for record in records:
        value = (record.get("metadata") or {}).get("source_quality_score")
        try:
            quality_values.append(float(value))
        except (TypeError, ValueError):
            continue
    findings: list[dict[str, Any]] = []
    minimum_unique_domains = config.get("minimum_unique_domains")
    if minimum_unique_domains not in (None, "") and len([d for d in domains if d != "__missing__"]) < int(minimum_unique_domains):
        findings.append({"type": "unique_domains", "count": len(domains), "minimum": int(minimum_unique_domains)})
    max_share_per_domain = config.get("max_share_per_domain")
    if max_share_per_domain not in (None, "") and total:
        max_share = float(max_share_per_domain)
        for domain, count in domains.items():
            if domain == "__missing__":
                continue
            share = count / total
            if share > max_share:
                findings.append({"type": "domain_concentration", "domain": domain, "count": count, "share": round(share, 4), "max_share": max_share})
    min_traceable = config.get("minimum_traceable_record_share")
    traceable_share = traceable / total if total else 0.0
    if min_traceable not in (None, "") and traceable_share < float(min_traceable):
        findings.append({"type": "traceability", "share": round(traceable_share, 4), "minimum_share": float(min_traceable)})
    min_evidence = config.get("minimum_evidence_linked_share")
    evidence_share = evidence_linked / total if total else 0.0
    if min_evidence not in (None, "") and evidence_share < float(min_evidence):
        findings.append({"type": "evidence_linkage", "share": round(evidence_share, 4), "minimum_share": float(min_evidence)})
    minimum_quality = config.get("minimum_source_quality_score")
    low_quality_count = 0
    if minimum_quality not in (None, ""):
        threshold = float(minimum_quality)
        low_quality_count = sum(1 for value in quality_values if value < threshold)
        if low_quality_count:
            findings.append({"type": "source_quality", "count": low_quality_count, "minimum_score": threshold})
    return {
        "domain_counts": counter_to_dict(domains),
        "unique_domains": len([d for d in domains if d != "__missing__"]),
        "traceable_record_share": round(traceable_share, 4),
        "evidence_linked_share": round(evidence_share, 4),
        "records_with_quality_score": len(quality_values),
        "low_quality_count": low_quality_count,
    }, findings

def float_percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(int(round((len(ordered) - 1) * fraction)), 0), len(ordered) - 1)
    return float(ordered[index])


def compute_dpo_coverage(
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pairs = [
        record for record in records
        if (record.get("response") or {}).get("format") == "preference_pair"
    ]
    pair_count = len(pairs)

    chosen_lengths: list[int] = []
    rejected_lengths: list[int] = []
    ratios: list[float] = []
    for record in pairs:
        response = record.get("response") or {}
        lc = len(str(response.get("chosen") or ""))
        lr = len(str(response.get("rejected") or ""))
        chosen_lengths.append(lc)
        rejected_lengths.append(lr)
        ratio = max(lc, lr) / max(1, min(lc, lr))
        ratios.append(ratio)

    mean_chosen_length = (sum(chosen_lengths) / pair_count) if pair_count else 0.0
    mean_rejected_length = (sum(rejected_lengths) / pair_count) if pair_count else 0.0
    length_ratio_p95 = float_percentile(ratios, 0.95) if ratios else 0.0

    dpo_delta_counts: Counter[str] = Counter()
    for record in pairs:
        delta = (record.get("metadata") or {}).get("dpo_delta")
        key = str(delta) if delta is not None else "__missing__"
        dpo_delta_counts[key] += 1

    findings: list[dict[str, Any]] = []
    dpo_config = plan.get("dpo") or {}

    min_pair_count = dpo_config.get("min_pair_count")
    if min_pair_count not in (None, "") and pair_count < int(min_pair_count):
        findings.append({"type": "dpo_pair_count", "count": pair_count, "minimum": int(min_pair_count)})

    max_mean_length_ratio = dpo_config.get("max_mean_length_ratio", 3.0)
    if max_mean_length_ratio not in (None, "") and mean_chosen_length > 0 and mean_rejected_length > 0:
        threshold = float(max_mean_length_ratio)
        actual_ratio = max(mean_chosen_length, mean_rejected_length) / min(mean_chosen_length, mean_rejected_length)
        if actual_ratio > threshold:
            findings.append({
                "type": "dpo_length_skew",
                "ratio": round(actual_ratio, 4),
                "max_mean_length_ratio": threshold,
            })

    max_share_per_delta = dpo_config.get("max_share_per_delta")
    if max_share_per_delta not in (None, "") and pair_count > 0:
        threshold = float(max_share_per_delta)
        for delta_value, count in dpo_delta_counts.items():
            share = count / pair_count
            if share > threshold:
                findings.append({
                    "type": "dpo_delta_concentration",
                    "delta": delta_value,
                    "share": round(share, 4),
                })

    return {
        "pair_count": pair_count,
        "mean_chosen_length": round(mean_chosen_length, 4),
        "mean_rejected_length": round(mean_rejected_length, 4),
        "length_ratio_p95": round(length_ratio_p95, 4),
        "dpo_delta_counts": counter_to_dict(dpo_delta_counts),
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
    response_length_findings: list[dict[str, Any]],
    response_structure_findings: list[dict[str, Any]],
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
    for item in response_length_findings:
        if item["type"] == "median_chars":
            recommendations.append(
                f"Shorten responses so median length falls below {item['max_median_chars']} characters."
            )
        elif item["type"] == "share_over_limit":
            recommendations.append(
                f"Reduce responses over {item['over_limit']} characters until they fall below {item['max_share']:.2f} share."
            )
    for item in response_structure_findings[:5]:
        recommendations.append(
            f"Diversify response structures so '{item['signature']}' falls below {item['max_share']:.2f} share."
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
        required_fields or DEFAULT_REQUIRED_FIELDS,
    )
    joint_group_counts, joint_coverage_gaps, joint_mode_collapse = compute_joint_groups(
        effective_records,
        plan,
    )
    provenance_summary, provenance_findings = compute_provenance(effective_records, plan)
    response_length_summary, response_length_findings = compute_response_length(effective_records, plan)
    response_structure_summary, response_structure_findings = compute_response_structure(effective_records, plan)
    response_prefix_summary, response_prefix_findings = compute_response_prefix(effective_records, plan)
    research_summary, research_findings = compute_research_coverage(effective_records, plan)
    dpo_summary, dpo_findings = compute_dpo_coverage(effective_records, plan)

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
        "response_length": response_length_summary,
        "response_length_findings": response_length_findings,
        "response_structure": response_structure_summary,
        "response_structure_findings": response_structure_findings,
        "response_prefix": response_prefix_summary,
        "response_prefix_findings": response_prefix_findings,
        "research": research_summary,
        "research_findings": research_findings,
        "dpo": dpo_summary,
        "dpo_findings": dpo_findings,
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
            response_length_findings=response_length_findings,
            response_structure_findings=response_structure_findings,
        ),
        "duplicates": duplicate_details[:50],
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
