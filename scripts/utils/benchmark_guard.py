from __future__ import annotations

import re
from typing import Any, Mapping

BENCHMARK_NAMES = ("humaneval", "human eval", "mbpp", "gsm8k", "mmlu", "arc challenge", "hellaswag")
PATTERNS = {
    "humaneval_function_name": re.compile(r"\b(has_close_elements|separate_paren_groups|truncate_number|below_zero|rescale_to_unit|filter_integers)\b", re.I),
    "canonical_multiple_choice": re.compile(r"\b(A\.|A\)|Option A)\s+.*\b(B\.|B\)|Option B)\s+.*\b(C\.|C\)|Option C)", re.I | re.S),
    "gsm8k_style": re.compile(r"\b(total|altogether|how many|left over)\b.*\b(show your work|step by step)\b", re.I | re.S),
}


def visible_text(record: Mapping[str, Any]) -> str:
    response = record.get("response") or {}
    if isinstance(response, Mapping) and response.get("format") == "preference_pair":
        answer = "\n".join([str(response.get("chosen") or ""), str(response.get("rejected") or "")])
    elif isinstance(response, Mapping):
        answer = str(response.get("text") or "")
    else:
        answer = str(response or "")
    return "\n".join([str(record.get("instruction") or ""), str(record.get("context") or ""), answer])


def contamination_findings(record: Mapping[str, Any]) -> list[str]:
    text = visible_text(record)
    lower = text.lower()
    findings = [f"benchmark_name:{name}" for name in BENCHMARK_NAMES if name in lower]
    findings.extend(name for name, pattern in PATTERNS.items() if pattern.search(text))
    return sorted(set(findings))


def benchmark_contamination_errors(record: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    config = plan.get("benchmark_contamination") or {}
    if not isinstance(config, Mapping) or not config.get("enabled"):
        return []
    findings = contamination_findings(record)
    if not findings:
        return []
    if config.get("blocking", True):
        return ["possible benchmark contamination: " + ", ".join(findings)]
    metadata = record.setdefault("metadata", {}) if isinstance(record, dict) else {}
    if isinstance(metadata, dict):
        metadata["benchmark_contamination_findings"] = findings
        metadata["requires_manual_review"] = True
    return []
