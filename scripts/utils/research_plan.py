from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_RESEARCH_EXPANSIONS = (
    "real-world examples",
    "edge cases",
    "failure modes",
    "bug reports",
    "forum discussions",
    "case studies",
    "best practices",
    "common mistakes",
)


def load_json_object(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _clean(value: Any) -> str:
    return " ".join(str(value).strip().split())


def _iter_taxonomy_values(payload: Mapping[str, Any]) -> Iterable[str]:
    group_minimums = payload.get("group_minimums") or {}
    if isinstance(group_minimums, Mapping):
        for expected in group_minimums.values():
            if isinstance(expected, Mapping):
                for value in expected.keys():
                    text = _clean(value)
                    if text and text != "__missing__":
                        yield text
    for rule in payload.get("joint_group_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        minimums = rule.get("minimums") or {}
        if isinstance(minimums, Mapping):
            for value in minimums.keys():
                for part in str(value).replace("::", " ").split():
                    text = _clean(part)
                    if text and text != "__missing__":
                        yield text
    taxonomy = payload.get("taxonomy") or {}
    if isinstance(taxonomy, Mapping):
        for values in taxonomy.values():
            if isinstance(values, list):
                for value in values:
                    text = _clean(value)
                    if text:
                        yield text


def build_research_plan(
    *,
    query: str,
    plan: Mapping[str, Any] | None = None,
    taxonomy: Mapping[str, Any] | None = None,
    max_subqueries: int = 12,
) -> dict[str, Any]:
    """Build deterministic research subqueries from a dataset request and coverage plan.

    This keeps the default research module LLM-free while borrowing GPT Researcher's
    useful planner/executor idea: broaden a single request into multiple evidence-
    seeking subquestions before crawling.
    """
    query = _clean(query)
    plan = dict(plan or {})
    taxonomy = dict(taxonomy or {})
    combined = {**taxonomy, **plan}

    candidates: list[str] = []
    if query:
        candidates.append(query)
        for expansion in DEFAULT_RESEARCH_EXPANSIONS:
            candidates.append(f"{query} {expansion}")

    for value in _iter_taxonomy_values(combined):
        if query:
            candidates.append(f"{query} {value} real-world example")
            candidates.append(f"{query} {value} edge case")
        else:
            candidates.append(value)

    seen: set[str] = set()
    subqueries: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        text = _clean(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        subqueries.append(
            {
                "id": f"rq_{len(subqueries) + 1:03d}",
                "query": text,
                "purpose": "primary" if len(subqueries) == 0 else "coverage_expansion",
            }
        )
        if len(subqueries) >= max_subqueries:
            break

    return {
        "query": query,
        "max_subqueries": max_subqueries,
        "subqueries": subqueries,
        "strategy": "deterministic planner: base query + real-world/edge-case/taxonomy expansions",
    }
