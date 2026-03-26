from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class SimilarityIndex:
    exact_seen: dict[str, str] = field(default_factory=dict)
    shingles_by_id: dict[str, set[str]] = field(default_factory=dict)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def shingle_set(text: str, *, size: int = 3) -> set[str]:
    tokens = tokenize(text)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def add_to_similarity_index(index: SimilarityIndex, *, record_id: str, text: str) -> None:
    index.exact_seen[hash_text(text)] = record_id
    index.shingles_by_id[record_id] = shingle_set(text)


def build_similarity_index(
    records: list[Mapping[str, Any]],
    *,
    text_fn: Callable[[Mapping[str, Any]], str],
) -> SimilarityIndex:
    index = SimilarityIndex()
    for record in records:
        record_id = str(record.get("id", "")).strip()
        if not record_id:
            continue
        add_to_similarity_index(index, record_id=record_id, text=text_fn(record))
    return index


def find_duplicate_for_text(
    index: SimilarityIndex,
    *,
    record_id: str,
    text: str,
    threshold: float,
) -> dict[str, Any] | None:
    exact_hash = hash_text(text)
    exact_match = index.exact_seen.get(exact_hash)
    if exact_match and exact_match != record_id:
        return {
            "kept_id": exact_match,
            "reason": "exact",
            "score": 1.0,
        }

    shingles = shingle_set(text)
    best_match: dict[str, Any] | None = None
    for kept_id, kept_tokens in index.shingles_by_id.items():
        if kept_id == record_id:
            continue
        score = similarity(shingles, kept_tokens)
        if score < threshold:
            continue
        if best_match is None or score > float(best_match["score"]):
            best_match = {
                "kept_id": kept_id,
                "reason": "near",
                "score": score,
            }
    return best_match


def find_duplicates(
    records: list[Mapping[str, Any]],
    *,
    threshold: float,
    text_fn: Callable[[Mapping[str, Any]], str],
) -> tuple[list[str], list[dict[str, Any]]]:
    kept_ids: list[str] = []
    duplicate_details: list[dict[str, Any]] = []
    index = SimilarityIndex()

    for record in records:
        record_id = str(record.get("id", "")).strip()
        if not record_id:
            continue

        match = find_duplicate_for_text(
            index,
            record_id=record_id,
            text=text_fn(record),
            threshold=threshold,
        )
        if match:
            duplicate_details.append(
                {
                    "duplicate_id": record_id,
                    "kept_id": str(match["kept_id"]),
                    "reason": str(match["reason"]),
                    "score": round(float(match["score"]), 4),
                }
            )
            continue

        kept_ids.append(record_id)
        add_to_similarity_index(index, record_id=record_id, text=text_fn(record))

    return kept_ids, duplicate_details
