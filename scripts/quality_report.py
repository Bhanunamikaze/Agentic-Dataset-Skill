from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.benchmark_guard import contamination_findings
from scripts.utils.code_quality import code_fingerprint
from scripts.utils.files import load_records, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a deterministic production quality report for canonical records.")
    parser.add_argument("--input", required=True, help="Canonical JSON/JSONL/CSV records.")
    parser.add_argument("--report", help="Optional JSON report path.")
    return parser.parse_args()


def response_text(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return "\n".join([str(response.get("chosen") or ""), str(response.get("rejected") or "")])
    return str(response.get("text") or "")


def main() -> None:
    args = parse_args()
    records = [dict(item) for item in load_records(args.input)]
    domains = Counter(str((record.get("metadata") or {}).get("source_domain") or "__missing__") for record in records)
    labels = Counter(str((record.get("metadata") or {}).get("label") or response_text(record).strip()[:80]) for record in records)
    lengths = [len(response_text(record)) for record in records]
    benchmark_hits = {str(record.get("id")): contamination_findings(record) for record in records if contamination_findings(record)}
    code_fps = Counter(code_fingerprint(response_text(record)) for record in records if "```" in response_text(record))
    summary: dict[str, Any] = {
        "records": len(records),
        "response_length_median": int(statistics.median(lengths)) if lengths else 0,
        "response_length_p90": sorted(lengths)[int(0.9 * (len(lengths) - 1))] if lengths else 0,
        "source_domains": dict(domains.most_common(20)),
        "top_labels_or_answers": dict(labels.most_common(20)),
        "benchmark_hits": benchmark_hits,
        "duplicate_code_fingerprints": {k: v for k, v in code_fps.items() if v > 1},
        "recommendations": [],
    }
    if benchmark_hits:
        summary["recommendations"].append("Re-draft records that match benchmark fingerprints.")
    if domains and domains.most_common(1)[0][1] / max(len(records), 1) > 0.4:
        summary["recommendations"].append("Increase source-domain diversity; one domain dominates the corpus.")
    if any(v > 1 for v in code_fps.values()):
        summary["recommendations"].append("Run dedup with --strategy code for code-heavy records.")
    if args.report:
        write_json(args.report, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
