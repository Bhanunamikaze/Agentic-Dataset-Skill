from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export import get_cluster_key
from scripts.utils.canonical import normalize_record, row_to_record
from scripts.utils.db import fetch_records_by_status, get_connection, initialize_database
from scripts.utils.files import load_records, write_json

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)

# Stopword filter for context-leakage detection. Common short words add noise
# without signaling that the answer was copied into the context.
LEAKAGE_STOPWORDS = frozenset(
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
    parser = argparse.ArgumentParser(description="Deterministic corpus-level dataset audit.")
    parser.add_argument("--input", help="Optional canonical/input records to audit.")
    parser.add_argument("--train", help="Canonical train JSONL for split leakage audit.")
    parser.add_argument("--test", help="Canonical test JSONL for split leakage audit.")
    parser.add_argument("--from-status", action="append", default=[], help="SQLite statuses to audit.")
    parser.add_argument("--source-run-id", help="Filter SQLite rows to one run.")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--db", help="Optional SQLite DB path.")
    parser.add_argument("--report", default="workspace/audit_report.json")
    parser.add_argument("--markdown-report", default="workspace/AUDIT_REPORT.md")
    return parser.parse_args()


def response_text(record: dict[str, Any]) -> str:
    response = record.get("response") or {}
    if response.get("format") == "preference_pair":
        return "\n".join([str(response.get("chosen") or ""), str(response.get("rejected") or "")])
    return str(response.get("text") or "")


def load_audit_records(args: argparse.Namespace) -> list[dict[str, Any]]:
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


def domain_for_record(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") or {}
    if metadata.get("source_domain"):
        return str(metadata["source_domain"])
    uri = str(record.get("source_uri") or "")
    return urlparse(uri).netloc.lower().removeprefix("www.") if uri else "__missing__"


def add_finding(findings: list[dict[str, Any]], severity: str, check: str, detail: str) -> None:
    findings.append({"severity": severity, "check": check, "detail": detail})


def split_disjointness(train_path: str | None, test_path: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not train_path or not test_path or not Path(train_path).exists() or not Path(test_path).exists():
        return None, []
    train = [normalize_record(item, allow_injections=True) for item in load_records(train_path)]
    test = [normalize_record(item, allow_injections=True) for item in load_records(test_path)]
    train_keys = Counter(get_cluster_key(record) for record in train)
    test_keys = Counter(get_cluster_key(record) for record in test)
    overlap = sorted(set(train_keys) & set(test_keys))
    findings: list[dict[str, Any]] = []
    if overlap:
        add_finding(findings, "High", "Split disjointness", f"{len(overlap)} scenario cluster keys appear in both train and test")
    return {"train_clusters": len(train_keys), "test_clusters": len(test_keys), "overlap": overlap[:50]}, findings


def taxonomy_findings(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    subtopics = Counter(str((record.get("metadata") or {}).get("subtopic") or "__missing__") for record in records)
    if records:
        for value, count in subtopics.items():
            share = count / len(records)
            if value != "__missing__" and share > 0.6:
                add_finding(findings, "Medium", "Taxonomy balance", f"metadata.subtopic={value} holds {share:.1%} of records")
        if subtopics.get("__missing__", 0) / len(records) > 0.2:
            add_finding(findings, "Medium", "Taxonomy metadata", "More than 20% of records are missing metadata.subtopic")
    return {"subtopic_counts": dict(subtopics)}, findings


def source_findings(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    domains = Counter(domain_for_record(record) for record in records)
    real_world = sum(1 for record in records if (record.get("metadata") or {}).get("source_origin") == "real_world")
    linked = sum(1 for record in records if (record.get("metadata") or {}).get("evidence_ids"))
    total = len(records)
    if total:
        real_share = real_world / total
        linked_share = linked / total
        if real_share < 0.4:
            add_finding(findings, "Medium", "Real-world grounding", f"Only {real_share:.1%} of records are marked real_world")
        if linked_share < 0.5:
            add_finding(findings, "Medium", "Evidence linkage", f"Only {linked_share:.1%} of records have evidence_ids")
        top_domain, top_count = domains.most_common(1)[0] if domains else ("__missing__", 0)
        if top_domain != "__missing__" and top_count / total > 0.35:
            add_finding(findings, "Medium", "Source diversity", f"Domain {top_domain} holds {top_count / total:.1%} of records")
    return {"domain_counts": dict(domains), "real_world_count": real_world, "evidence_linked_count": linked}, findings


def label_balance(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels = Counter()
    for record in records:
        metadata = record.get("metadata") or {}
        label = metadata.get("label")
        text = response_text(record).strip()
        if label:
            labels[str(label)] += 1
        elif text and len(text.split()) <= 3 and len(text) <= 40:
            labels[text] += 1
    findings: list[dict[str, Any]] = []
    total = sum(labels.values())
    if total and 1 < len(labels) <= 12:
        value, count = labels.most_common(1)[0]
        share = count / total
        if share > 0.75:
            add_finding(findings, "High", "Label balance", f"Label {value!r} holds {share:.1%} of classification-like records")
        elif share > 0.60:
            add_finding(findings, "Medium", "Label balance", f"Label {value!r} holds {share:.1%} of classification-like records")
    return {"label_counts": dict(labels)}, findings


def synthetic_fingerprint(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    openings = Counter()
    lengths: list[int] = []
    polished = 0
    for record in records:
        instruction = str(record.get("instruction") or "")
        if instruction and instruction[:1].isupper() and instruction.endswith(('.', '?', '!')):
            polished += 1
        text = " ".join(response_text(record).split())
        if text:
            openings[text[:48].lower()] += 1
            lengths.append(len(text))
    findings: list[dict[str, Any]] = []
    total = len(records)
    repeated_share = (openings.most_common(1)[0][1] / total) if openings and total else 0.0
    polished_share = polished / total if total else 0.0
    cv = (statistics.pstdev(lengths) / statistics.mean(lengths)) if len(lengths) > 1 and statistics.mean(lengths) else 0.0
    score = 0
    if repeated_share > 0.3:
        score += 35
        add_finding(findings, "Medium", "Synthetic fingerprint", f"Top response opening appears in {repeated_share:.1%} of records")
    if polished_share > 0.8:
        score += 25
        add_finding(findings, "Low", "Instruction naturalness", f"{polished_share:.1%} of instructions look fully polished")
    if cv and cv < 0.2:
        score += 20
        add_finding(findings, "Low", "Response length variance", f"Response length CV is {cv:.2f}; likely templated")
    severity = "High" if score > 70 else "Medium" if score >= 40 else None
    if severity:
        add_finding(findings, severity, "Synthetic score", f"Synthetic fingerprint score is {score}/100")
    return {"synthetic_score": score, "repeated_opening_share": round(repeated_share, 4), "polished_instruction_share": round(polished_share, 4), "response_length_cv": round(cv, 4)}, findings


def cluster_fallback_findings(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Flag when too many records fall back to instruction-word cluster keys."""
    from scripts.export import get_cluster_key
    findings: list[dict[str, Any]] = []
    if not records:
        return {"fallback_count": 0, "fallback_share": 0.0}, findings
    fallback_count = sum(1 for r in records if get_cluster_key(r).startswith("fallback:"))
    fallback_share = fallback_count / len(records)
    if fallback_share > 0.25:
        add_finding(
            findings,
            "Medium",
            "Cluster fallback overuse",
            f"{fallback_share:.1%} of records use fallback cluster keys. "
            "Add metadata.scenario_fingerprint, metadata.topic, or metadata.evidence_ids to reduce split leakage risk.",
        )
    return {
        "fallback_count": fallback_count,
        "fallback_share": round(fallback_share, 4),
    }, findings


def _response_content_tokens(text: str) -> set[str]:
    """Distinct decisive tokens from a response: length >= 5, no stopwords."""
    return {
        item
        for item in TOKEN_RE.findall(text.lower())
        if len(item) >= 5 and item not in LEAKAGE_STOPWORDS
    }


def context_leakage_findings(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Detect records whose context contains decisive answer tokens.

    sub-skills/dataset-auditor.md section 2C describes this check. The earlier
    audit script only inspected metadata; this catches records where the
    answer was copied into the prompt, which inflates eval scores.
    """
    findings: list[dict[str, Any]] = []
    if not records:
        return {"leaked_count": 0, "leaked_share": 0.0, "examined": 0}, findings

    leaked = 0
    examined = 0
    leaked_ids: list[str] = []
    for record in records:
        context = str(record.get("context") or "").strip()
        if not context:
            continue
        examined += 1
        decisive_tokens = _response_content_tokens(response_text(record))
        if not decisive_tokens:
            continue
        ctx_lower = context.lower()
        decisive_hits = sum(1 for token in decisive_tokens if token in ctx_lower)
        if decisive_hits >= 3:
            leaked += 1
            if len(leaked_ids) < 25:
                leaked_ids.append(str(record.get("id") or ""))
    share = (leaked / examined) if examined else 0.0
    if examined and share > 0.25:
        add_finding(
            findings,
            "High",
            "Context leakage",
            f"{share:.1%} of records with non-empty context contain >=3 decisive answer tokens; trim the context or rewrite responses.",
        )
    elif examined and share > 0.10:
        add_finding(
            findings,
            "Medium",
            "Context leakage",
            f"{share:.1%} of records with non-empty context contain >=3 decisive answer tokens; review before training.",
        )
    return {
        "leaked_count": leaked,
        "examined": examined,
        "leaked_share": round(share, 4),
        "sample_leaked_ids": leaked_ids,
    }, findings


def write_markdown(path: str, summary: dict[str, Any]) -> None:
    lines = [
        "# Dataset Audit Report",
        "",
        f"**Total records reviewed**: {summary['total_records']}",
        "",
        "## Findings",
        "",
        "| # | Severity | Check | Detail |",
        "|---|---|---|---|",
    ]
    for index, finding in enumerate(summary["findings"], start=1):
        detail = str(finding["detail"]).replace("|", "\\|")
        lines.append(f"| {index} | {finding['severity']} | {finding['check']} | {detail} |")
    if not summary["findings"]:
        lines.append("| 1 | Pass | Deterministic audit | No blocking findings detected |")
    lines.extend(["", "## Metrics", "", "```json", json.dumps(summary["metrics"], indent=2), "```", ""])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    records = load_audit_records(args)
    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    split_summary, split_findings = split_disjointness(args.train, args.test)
    if split_summary:
        metrics["split_disjointness"] = split_summary
    findings.extend(split_findings)
    for name, fn in (
        ("taxonomy", taxonomy_findings),
        ("sources", source_findings),
        ("labels", label_balance),
        ("synthetic", synthetic_fingerprint),
        ("cluster_keys", cluster_fallback_findings),
        ("context_leakage", context_leakage_findings),
    ):
        result, result_findings = fn(records)
        metrics[name] = result
        findings.extend(result_findings)
    summary = {"total_records": len(records), "metrics": metrics, "findings": findings}
    write_json(args.report, summary)
    write_markdown(args.markdown_report, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
