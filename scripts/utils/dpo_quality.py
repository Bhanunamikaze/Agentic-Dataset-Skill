from __future__ import annotations

import re
from typing import Any, Mapping

REFUSAL_RE = re.compile(r"\b(i cannot|i can'?t|as an ai|sorry,? but|unable to comply)\b", re.I)


def dpo_pair_errors(record: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    config = plan.get("dpo_audit") or plan.get("dpo") or {}
    if not isinstance(config, Mapping):
        return []
    
    enabled = config.get("enabled")
    if enabled is None:
        enabled = len(config) > 0
        
    if not enabled:
        return []
        
    response = record.get("response") or {}
    if not isinstance(response, Mapping) or response.get("format") != "preference_pair":
        return []
    chosen = str(response.get("chosen") or "").strip()
    rejected = str(response.get("rejected") or "").strip()
    errors: list[str] = []
    if not chosen or not rejected:
        errors.append("DPO chosen/rejected response is empty")
    if chosen == rejected:
        errors.append("DPO chosen and rejected are identical")
    min_chosen_chars = int(config.get("min_chosen_chars", 40))
    if len(chosen) < min_chosen_chars:
        errors.append(f"DPO chosen response is too short for a useful positive (< {min_chosen_chars} chars)")
    min_rejected_chars = int(config.get("min_rejected_chars", 40))
    if len(rejected) < min_rejected_chars:
        errors.append(f"DPO rejected response is too short for a plausible hard negative (< {min_rejected_chars} chars)")
    max_ratio = float(config.get("max_length_ratio", 3.0))
    if chosen and rejected:
        ratio = max(len(chosen), len(rejected)) / max(min(len(chosen), len(rejected)), 1)
        if ratio > max_ratio:
            errors.append(f"DPO chosen/rejected length ratio {ratio:.2f} exceeds {max_ratio:.2f}")
            
    require_delta = config.get("require_delta")
    if require_delta is None:
        require_delta = config.get("require_dpo_delta")
    if require_delta is None:
        require_delta = "dpo_audit" in plan
        
    if require_delta and not (record.get("metadata") or {}).get("dpo_delta"):
        errors.append("DPO record missing metadata.dpo_delta")
        
    forbid_refusal = config.get("forbid_refusal_in_rejected", True)
    if forbid_refusal and REFUSAL_RE.search(rejected):
        errors.append("DPO rejected response looks like a refusal instead of a plausible hard negative")
    # A refusal in the chosen response is worse than one in rejected: it teaches
    # the model to refuse the correct answer. Always flag it.
    if REFUSAL_RE.search(chosen):
        errors.append("DPO chosen response looks like a refusal; the chosen side must demonstrate the target behavior")
    return errors
