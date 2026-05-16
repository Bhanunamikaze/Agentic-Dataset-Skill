from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import normalize_record
from scripts.utils.coverage_plan import (
    ensure_string_list,
    is_missing_value,
    load_plan,
    resolve_path,
)
from scripts.utils.files import load_records, write_json
from scripts.verify import _TROPE_OPENERS, _refusal_match

# Lint dictionaries from sub-skills/seed-generator.md. These deliberately stay
# lowercase substring lists so the lint stays deterministic and IDE-friendly.
NEGATIVE_MARKERS = (
    "don't",
    "do not",
    "avoid",
    "without",
    "instead of",
)
FORMAT_MARKERS = (
    "return only",
    "respond in",
    "exactly",
    "json",
    "bullet",
)
SCOPING_MARKERS = (
    "assume",
    "given",
    "in python",
    "version",
)

DEFAULT_REQUIRED_FIELDS = [
    "metadata.difficulty",
    "metadata.persona",
    "metadata.subtopic",
    "metadata.intent",
    "metadata.response_shape",
    "metadata.instruction_fidelity",
    "metadata.source_origin",
]

MESSY_FIDELITY_VALUES = ("messy", "casual", "ambiguous")
PLACEHOLDER_PATTERN = "[PENDING_"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-import lint pass that flags drafted records before they enter the SQLite pipeline."
    )
    parser.add_argument("--input", required=True, help="Draft JSONL/JSON/CSV file to lint.")
    parser.add_argument("--plan-file", help="Optional coverage/quality plan overriding default rules.")
    parser.add_argument("--report", help="Optional path to write a JSON summary report.")
    return parser.parse_args()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("id") or "")


def _violation(
    rule: str,
    count: int,
    total: int,
    sample_ids: list[str],
    detail: str,
) -> dict[str, Any]:
    share = round(count / total, 4) if total else 0.0
    return {
        "rule": rule,
        "count": count,
        "share": share,
        "sample_ids": sample_ids[:5],
        "detail": detail,
    }


def _response_text_pieces(record: dict[str, Any]) -> list[str]:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return [str(response.get("chosen") or ""), str(response.get("rejected") or "")]
    return [str(response.get("text") or "")]


def lint_multi_constraint(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    offenders: list[str] = []
    for record in records:
        instruction = str(record.get("instruction") or "").lower()
        matched = sum(
            1
            for markers in (NEGATIVE_MARKERS, FORMAT_MARKERS, SCOPING_MARKERS)
            if _contains_any(instruction, markers)
        )
        if matched < 2:
            offenders.append(_record_id(record))
    if not offenders:
        return None
    return _violation(
        "multi_constraint",
        len(offenders),
        len(records),
        offenders,
        "Instructions lack at least 2 of (negative, format, scoping) constraints.",
    )


def lint_trope_opener(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    offenders: list[str] = []
    for record in records:
        for text in _response_text_pieces(record):
            head = text.strip().lower()
            if any(head.startswith(marker) for marker in _TROPE_OPENERS):
                offenders.append(_record_id(record))
                break
    if not offenders:
        return None
    return _violation(
        "trope_opener",
        len(offenders),
        len(records),
        offenders,
        "Response begins with a known LLM trope opener (see verify._TROPE_OPENERS).",
    )


def lint_missing_required_metadata(
    records: list[dict[str, Any]], required_fields: list[str]
) -> dict[str, Any] | None:
    offenders: list[str] = []
    per_field_counts: Counter[str] = Counter()
    for record in records:
        missing_here = [
            field for field in required_fields if is_missing_value(resolve_path(record, field))
        ]
        if missing_here:
            offenders.append(_record_id(record))
            for field in missing_here:
                per_field_counts[field] += 1
    if not offenders:
        return None
    detail_fields = ", ".join(
        f"{field}={count}" for field, count in per_field_counts.most_common(5)
    )
    return _violation(
        "missing_required_metadata",
        len(offenders),
        len(records),
        offenders,
        f"Required metadata fields absent: {detail_fields}",
    )


def lint_response_shape_skew(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    counter: Counter[str] = Counter()
    for record in records:
        shape = (record.get("metadata") or {}).get("response_shape")
        if shape:
            counter[str(shape)] += 1
    total = sum(counter.values())
    if not total:
        return None
    for shape, count in counter.most_common(1):
        share = count / total
        if share > 0.4:
            sample_ids = [
                _record_id(record)
                for record in records
                if str((record.get("metadata") or {}).get("response_shape") or "") == shape
            ][:5]
            return _violation(
                "response_shape_skew",
                count,
                len(records),
                sample_ids,
                f"Response shape {shape!r} accounts for {share:.2%} of the batch (cap 40%).",
            )
    return None


def lint_instruction_fidelity_underspread(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    counter: Counter[str] = Counter()
    for record in records:
        fidelity = (record.get("metadata") or {}).get("instruction_fidelity")
        if fidelity:
            counter[str(fidelity).lower()] += 1
    if not records:
        return None
    messy_count = sum(counter.get(value, 0) for value in MESSY_FIDELITY_VALUES)
    share = messy_count / len(records)
    if share >= 0.20:
        return None
    sample_ids = [_record_id(record) for record in records[:5]]
    return _violation(
        "instruction_fidelity_underspread",
        messy_count,
        len(records),
        sample_ids,
        f"messy+casual+ambiguous share is {share:.2%}, below 20% spread minimum.",
    )


def lint_no_real_world_source(
    records: list[dict[str, Any]], minimum_share: float
) -> dict[str, Any] | None:
    real_world = [
        record
        for record in records
        if str((record.get("metadata") or {}).get("source_origin") or "") == "real_world"
    ]
    if not records:
        return None
    share = len(real_world) / len(records)
    if share >= minimum_share:
        return None
    sample_ids = [_record_id(record) for record in records if record not in real_world][:5]
    return _violation(
        "no_real_world_source",
        len(records) - len(real_world),
        len(records),
        sample_ids,
        f"real_world share is {share:.2%}, below required {minimum_share:.2%}.",
    )


def lint_preference_pair_missing_dpo_delta(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    offenders: list[str] = []
    pair_count = 0
    for record in records:
        response = record.get("response") or {}
        if response.get("format") != "preference_pair":
            continue
        pair_count += 1
        if not (record.get("metadata") or {}).get("dpo_delta"):
            offenders.append(_record_id(record))
    if not offenders:
        return None
    return _violation(
        "preference_pair_missing_dpo_delta",
        len(offenders),
        pair_count or len(records),
        offenders,
        "DPO records must populate metadata.dpo_delta.",
    )


def lint_preference_pair_chosen_refusal(
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    offenders: list[str] = []
    pair_count = 0
    for record in records:
        response = record.get("response") or {}
        if response.get("format") != "preference_pair":
            continue
        pair_count += 1
        chosen = str(response.get("chosen") or "")
        if _refusal_match(chosen) is not None:
            offenders.append(_record_id(record))
    if not offenders:
        return None
    return _violation(
        "preference_pair_chosen_refusal",
        len(offenders),
        pair_count or len(records),
        offenders,
        "DPO chosen text matched a refusal pattern.",
    )


def lint_preference_pair_short_chosen(
    records: list[dict[str, Any]], min_chosen_chars: int
) -> dict[str, Any] | None:
    offenders: list[str] = []
    pair_count = 0
    for record in records:
        response = record.get("response") or {}
        if response.get("format") != "preference_pair":
            continue
        pair_count += 1
        chosen = str(response.get("chosen") or "")
        if len(chosen) < min_chosen_chars:
            offenders.append(_record_id(record))
    if not offenders:
        return None
    return _violation(
        "preference_pair_short_chosen",
        len(offenders),
        pair_count or len(records),
        offenders,
        f"DPO chosen response shorter than {min_chosen_chars} characters.",
    )


def lint_placeholder_or_pending(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    offenders: list[str] = []
    for record in records:
        haystack_parts = [
            str(record.get("instruction") or ""),
            str(record.get("context") or ""),
            *_response_text_pieces(record),
        ]
        if any(PLACEHOLDER_PATTERN in part for part in haystack_parts):
            offenders.append(_record_id(record))
    if not offenders:
        return None
    return _violation(
        "placeholder_or_pending",
        len(offenders),
        len(records),
        offenders,
        "Records still contain [PENDING_*] placeholder markers.",
    )


def _recommendation_for(violation: dict[str, Any]) -> str:
    rule = violation["rule"]
    if rule == "multi_constraint":
        return "Re-draft instructions to carry at least 2 of negative/format/scoping constraints (see seed-generator.md)."
    if rule == "trope_opener":
        return "Strip trope openers ('As an AI…', 'Certainly!', 'Here is…') before importing the batch."
    if rule == "missing_required_metadata":
        return "Backfill required metadata fields on every drafted record (difficulty, persona, subtopic, intent, response_shape, instruction_fidelity, source_origin)."
    if rule == "response_shape_skew":
        return "Diversify metadata.response_shape so no single shape exceeds 40% of the batch."
    if rule == "instruction_fidelity_underspread":
        return "Inject more messy/casual/ambiguous instructions until they exceed 20% combined share."
    if rule == "no_real_world_source":
        return "Ground more records in real-world sources before importing (target real_world share >= plan minimum)."
    if rule == "preference_pair_missing_dpo_delta":
        return "Add metadata.dpo_delta tags to every DPO record so contrastive coverage is auditable."
    if rule == "preference_pair_chosen_refusal":
        return "Rewrite the chosen response so it no longer reads as a refusal."
    if rule == "preference_pair_short_chosen":
        return "Lengthen DPO chosen responses to clear the plan.dpo_audit.min_chosen_chars threshold."
    if rule == "placeholder_or_pending":
        return "Fill in [PENDING_*] placeholders with real content before importing."
    return f"Resolve violations for rule {rule}."


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    raw_records = load_records(args.input)
    records = [
        normalize_record(
            item,
            default_task_type=str(item.get("task_type", "sft")),
            source_type=str(item.get("source_type", "generated")),
            allow_injections=True,
        )
        for item in raw_records
    ]

    draft_config = plan.get("draft_self_check") or {}
    required_fields = ensure_string_list(draft_config.get("required_fields")) or DEFAULT_REQUIRED_FIELDS
    provenance = plan.get("provenance") or {}
    minimum_real_world_share = float(
        draft_config.get("minimum_real_world_share")
        or provenance.get("minimum_real_world_share")
        or 0.6
    )
    dpo_audit = plan.get("dpo_audit") or {}
    min_chosen_chars = int(dpo_audit.get("min_chosen_chars") or 40)

    violations: list[dict[str, Any]] = []
    candidates = [
        lint_multi_constraint(records),
        lint_trope_opener(records),
        lint_missing_required_metadata(records, required_fields),
        lint_response_shape_skew(records),
        lint_instruction_fidelity_underspread(records),
        lint_no_real_world_source(records, minimum_real_world_share),
        lint_preference_pair_missing_dpo_delta(records),
        lint_preference_pair_chosen_refusal(records),
        lint_preference_pair_short_chosen(records, min_chosen_chars),
        lint_placeholder_or_pending(records),
    ]
    violations = [item for item in candidates if item is not None]

    # FAIL on any structural / placeholder violation; WARN on share-based ones; PASS otherwise.
    fail_rules = {
        "placeholder_or_pending",
        "preference_pair_chosen_refusal",
        "preference_pair_missing_dpo_delta",
        "missing_required_metadata",
    }
    has_fail = any(item["rule"] in fail_rules for item in violations)
    overall_status = "PASS"
    if violations and has_fail:
        overall_status = "FAIL"
    elif violations:
        overall_status = "WARN"

    sorted_violations = sorted(
        violations, key=lambda item: (-float(item["share"]), item["rule"])
    )
    recommendations = [_recommendation_for(item) for item in sorted_violations[:3]]

    summary: dict[str, Any] = {
        "input": args.input,
        "records_examined": len(records),
        "required_fields": required_fields,
        "minimum_real_world_share": minimum_real_world_share,
        "min_chosen_chars": min_chosen_chars,
        "violations": sorted_violations,
        "overall_status": overall_status,
        "recommendations": recommendations,
    }

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
