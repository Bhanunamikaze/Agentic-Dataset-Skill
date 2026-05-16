from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.files import load_records

# ---------------------------------------------------------------------------
# Canonical bucket definitions — substring matching, fully deterministic.
# Each entry is (bucket_name, tuple_of_lowercase_substrings).
# The first matching bucket wins; "other" is the catch-all.
# ---------------------------------------------------------------------------
BUCKET_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "vague_instruction",
        ("vague", "ambiguous", "unclear instruction", "too short instruction"),
    ),
    (
        "weak_response",
        ("weak response", "too short response", "minimal response", "generic response"),
    ),
    (
        "apology_opener",
        ("apology", "sorry", "apologize", "starts with i cannot"),
    ),
    (
        "trope_opener",
        ("trope", "great question", "certainly", "of course"),
    ),
    (
        "refusal_error",
        ("refusal", "refuses", "declines non-safety"),
    ),
    (
        "grounding_fail",
        ("grounding", "evidence", "hallucin", "unsupported claim"),
    ),
    (
        "dpo_quality",
        ("dpo", "chosen", "rejected", "delta"),
    ),
    (
        "format_violation",
        ("format", "json invalid", "bullet", "missing field"),
    ),
    (
        "leakage",
        ("leakage", "leaked", "context appears"),
    ),
]


def classify_reason(reason: str) -> str:
    """Map a raw fail_reason string to a canonical bucket name."""
    lowered = reason.lower()
    for bucket, keywords in BUCKET_RULES:
        if any(kw in lowered for kw in keywords):
            return bucket
    return "other"


_RECOMMENDATIONS: dict[str, str] = {
    "vague_instruction": (
        "{count} records failed vague_instruction — tighten instruction specificity"
        " in seed-generator prompts"
    ),
    "weak_response": (
        "{count} records failed weak_response — expand response depth and length"
        " in seed-generator drafts"
    ),
    "apology_opener": (
        "{count} records failed apology_opener — strip apology and 'I cannot' openers"
        " from response text before importing"
    ),
    "trope_opener": (
        "{count} records failed trope_opener — remove trope openers ('Great question!',"
        " 'Certainly!', 'Of course!') from responses"
    ),
    "refusal_error": (
        "{count} records failed refusal_error — rewrite refusals that decline"
        " non-safety requests into substantive answers"
    ),
    "grounding_fail": (
        "{count} records failed grounding_fail — ground responses in cited evidence"
        " and remove unsupported or hallucinated claims"
    ),
    "dpo_quality": (
        "{count} records failed dpo_quality — review DPO chosen/rejected pairs"
        " and ensure metadata.dpo_delta is populated"
    ),
    "format_violation": (
        "{count} records failed format_violation — fix JSON structure, bullet"
        " formatting, and missing required fields"
    ),
    "leakage": (
        "{count} records failed leakage — remove context leakage and"
        " answer-bearing lines from model-visible fields"
    ),
    "other": (
        "{count} records failed with uncategorised reasons — review fail_reasons"
        " manually and add bucket rules if a pattern emerges"
    ),
}


def build_recommendation(bucket: str, count: int) -> str:
    template = _RECOMMENDATIONS.get(
        bucket,
        f"{{count}} records failed {bucket} — investigate and fix the underlying issue",
    )
    return template.format(count=count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cluster fail_reasons from a review.jsonl LLM-judge output file and"
            " produce a structured JSON summary of failure patterns."
        )
    )
    parser.add_argument(
        "--review-file",
        required=True,
        help="Path to the review.jsonl file produced by the LLM judge.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to write the JSON summary (default: stdout).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Maximum number of failure pattern buckets to include in the output (default: 10).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    records = load_records(args.review_file)

    total = len(records)
    pass_count = sum(1 for r in records if str(r.get("verdict") or "").lower() == "pass")
    fail_count = total - pass_count
    pass_rate = round(pass_count / total, 4) if total else 0.0

    # Accumulate counts and examples per bucket across all failing records.
    bucket_counts: dict[str, int] = defaultdict(int)
    bucket_examples: dict[str, list[str]] = defaultdict(list)

    for record in records:
        if str(record.get("verdict") or "").lower() == "pass":
            continue
        fail_reasons: list[Any] = record.get("fail_reasons") or []
        if not isinstance(fail_reasons, list):
            fail_reasons = [str(fail_reasons)]
        for raw_reason in fail_reasons:
            reason_str = str(raw_reason).strip()
            if not reason_str:
                continue
            bucket = classify_reason(reason_str)
            bucket_counts[bucket] += 1
            examples = bucket_examples[bucket]
            if reason_str not in examples and len(examples) < 3:
                examples.append(reason_str)

    # Sort buckets by count descending, cap at --top-n.
    sorted_buckets = sorted(bucket_counts.items(), key=lambda item: -item[1])
    top_patterns: list[dict[str, Any]] = [
        {
            "bucket": bucket,
            "count": count,
            "examples": bucket_examples[bucket],
        }
        for bucket, count in sorted_buckets[: args.top_n]
    ]

    recommendations: list[str] = [
        build_recommendation(pattern["bucket"], pattern["count"])
        for pattern in top_patterns
    ]

    summary: dict[str, Any] = {
        "total": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate": pass_rate,
        "top_failure_patterns": top_patterns,
        "recommendations": recommendations,
    }

    output_text = json.dumps(summary, indent=2, ensure_ascii=True) + "\n"

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)


if __name__ == "__main__":
    main()
