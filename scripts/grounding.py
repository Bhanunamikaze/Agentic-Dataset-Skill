from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import normalize_record, row_to_record
from scripts.utils.coverage_plan import load_plan
from scripts.utils.db import fetch_records_by_status, get_connection, initialize_database
from scripts.utils.files import load_records, write_json

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)

# Content-bearing token filter for grounding overlap. Stopwords and short
# connectors pad the overlap score without contributing factual signal, so we
# drop them when measuring response-vs-evidence agreement.
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "this", "that", "from", "into", "your",
        "have", "has", "had", "are", "was", "were", "but", "not", "you",
        "their", "they", "them", "its", "our", "any", "all", "can", "will",
        "would", "should", "could", "may", "might", "also", "than", "then",
        "what", "when", "which", "where", "why", "how", "who", "whom",
        "about", "after", "before", "between", "such", "some", "much",
        "many", "more", "most", "less", "least", "very", "just", "only",
        "other", "another", "each", "every", "both", "either", "neither",
        "there", "here", "while", "because", "since", "however", "thus",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check record grounding against evidence.jsonl.")
    parser.add_argument("--input", help="Optional JSON/JSONL/CSV records to check directly.")
    parser.add_argument("--evidence-file", required=True, help="research.py evidence.jsonl file.")
    parser.add_argument("--plan-file", help="Optional plan with grounding thresholds.")
    parser.add_argument("--from-status", action="append", default=[], help="SQLite statuses to check.")
    parser.add_argument("--source-run-id", help="Filter SQLite rows to one run.")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--db", help="Optional SQLite DB path.")
    parser.add_argument("--report", help="Optional JSON report path.")
    return parser.parse_args()


def tokens(text: str) -> set[str]:
    """Return content-bearing tokens: length >= 4 and not in the stopword list."""
    return {
        item
        for item in TOKEN_RE.findall(str(text or "").lower())
        if len(item) >= 4 and item not in STOPWORDS
    }


def response_text(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return "\n".join([str(response.get("chosen") or ""), str(response.get("rejected") or "")])
    return str(response.get("text") or "")


def load_evidence(path: str) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for row in load_records(path):
        evidence_id = row.get("evidence_id") or row.get("id")
        if evidence_id:
            evidence[str(evidence_id)] = dict(row)
    return evidence


def evidence_ids(record: dict[str, Any]) -> list[str]:
    metadata = record.get("metadata") or {}
    value = metadata.get("evidence_ids") or metadata.get("evidence_id") or []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def load_records_for_check(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input:
        return [normalize_record(item, source_type=str(item.get("source_type", "raw_dataset")), allow_injections=True) for item in load_records(args.input)]
    db_path = initialize_database(args.db) if args.db else initialize_database()
    connection = get_connection(db_path)
    try:
        rows = fetch_records_by_status(connection, tuple(args.from_status or ["verified_pass", "judge_pending", "raw_generated"]))
        if args.source_run_id:
            rows = [row for row in rows if row["run_id"] == args.source_run_id]
        return [row_to_record(dict(row)) for row in rows[: args.limit]]
    finally:
        connection.close()


def check_record(record: dict[str, Any], evidence_map: dict[str, dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    ids = evidence_ids(record)
    missing_ids = [item for item in ids if item not in evidence_map]
    joined_evidence = "\n".join(str(evidence_map[item].get("text") or "") for item in ids if item in evidence_map)
    record_tokens = tokens(response_text(record))
    evidence_tokens = tokens(joined_evidence)
    overlap = (len(record_tokens & evidence_tokens) / len(record_tokens)) if record_tokens else 0.0
    config = plan.get("grounding") or {}
    # Raised from 0.08 to 0.20: the legacy 0.08 default treated effectively any
    # response as grounded once stopwords were counted. 0.20 against the
    # content-bearing token set (>=4 chars, no stopwords) is a real lexical
    # signal that the response stayed near the cited evidence.
    min_overlap = float(config.get("minimum_response_evidence_overlap", 0.20) or 0.0)
    findings: list[str] = []
    if not ids:
        findings.append("missing evidence_ids")
    if missing_ids:
        findings.append("unknown evidence_ids: " + ", ".join(missing_ids))
    if ids and overlap < min_overlap:
        findings.append(f"low response/evidence lexical overlap: {overlap:.3f} < {min_overlap:.3f}")
    return {
        "id": record.get("id"),
        "evidence_ids": ids,
        "missing_evidence_ids": missing_ids,
        "response_evidence_overlap": round(overlap, 4),
        "status": "pass" if not findings else "fail",
        "findings": findings,
    }


def main() -> None:
    args = parse_args()
    plan = load_plan(args.plan_file)
    evidence_map = load_evidence(args.evidence_file)
    records = load_records_for_check(args)
    details = [check_record(record, evidence_map, plan) for record in records]
    failed = [item for item in details if item["status"] == "fail"]
    summary = {
        "records_checked": len(details),
        "evidence_chunks_loaded": len(evidence_map),
        "grounding_pass": len(details) - len(failed),
        "grounding_fail": len(failed),
        "details": details,
    }
    if args.report:
        write_json(args.report, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
