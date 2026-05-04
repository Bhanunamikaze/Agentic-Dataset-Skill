from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from scripts.utils.code_quality import code_fingerprint

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class SimilarityIndex:
    exact_seen: dict[str, str] = field(default_factory=dict)
    shingles_by_id: dict[str, set[str]] = field(default_factory=dict)
    token_counts_by_id: dict[str, Counter[str]] = field(default_factory=dict)
    code_fingerprints_by_id: dict[str, str] = field(default_factory=dict)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def shingle_set(text: str, *, size: int = 3) -> set[str]:
    tokens = tokenize(text)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def set_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine_counts(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[k] * right[k] for k in set(left) & set(right))
    left_norm = math.sqrt(sum(v * v for v in left.values()))
    right_norm = math.sqrt(sum(v * v for v in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def add_to_similarity_index(index: SimilarityIndex, *, record_id: str, text: str) -> None:
    index.exact_seen[hash_text(text)] = record_id
    index.shingles_by_id[record_id] = shingle_set(text)
    index.token_counts_by_id[record_id] = Counter(tokenize(text))
    index.code_fingerprints_by_id[record_id] = code_fingerprint(text)


def build_similarity_index(records: list[Mapping[str, Any]], *, text_fn: Callable[[Mapping[str, Any]], str]) -> SimilarityIndex:
    index = SimilarityIndex()
    for record in records:
        record_id = str(record.get("id", "")).strip()
        if record_id:
            add_to_similarity_index(index, record_id=record_id, text=text_fn(record))
    return index


def find_duplicate_for_text(index: SimilarityIndex, *, record_id: str, text: str, threshold: float, strategy: str = "shingle") -> dict[str, Any] | None:
    exact_match = index.exact_seen.get(hash_text(text))
    if exact_match and exact_match != record_id:
        return {"kept_id": exact_match, "reason": "exact", "score": 1.0}
    shingles = shingle_set(text)
    tokens = Counter(tokenize(text))
    code_fp = code_fingerprint(text)
    best: dict[str, Any] | None = None
    for kept_id, kept_shingles in index.shingles_by_id.items():
        if kept_id == record_id:
            continue
        if strategy == "tfidf":
            score = cosine_counts(tokens, index.token_counts_by_id.get(kept_id, Counter()))
            reason = "tfidf"
        elif strategy == "code":
            score = 1.0 if code_fp and code_fp == index.code_fingerprints_by_id.get(kept_id) else set_similarity(shingles, kept_shingles)
            reason = "code_fingerprint" if score == 1.0 else "code_fallback_near"
        else:
            score = set_similarity(shingles, kept_shingles)
            reason = "minhash_fallback" if strategy == "minhash" else "near"
        if score >= threshold and (best is None or score > float(best["score"])):
            best = {"kept_id": kept_id, "reason": reason, "score": score}
    return best


def find_duplicates(records: list[Mapping[str, Any]], *, threshold: float, text_fn: Callable[[Mapping[str, Any]], str], strategy: str = "shingle") -> tuple[list[str], list[dict[str, Any]]]:
    kept_ids: list[str] = []
    duplicates: list[dict[str, Any]] = []
    index = SimilarityIndex()
    for record in records:
        record_id = str(record.get("id", "")).strip()
        if not record_id:
            continue
        text = text_fn(record)
        match = find_duplicate_for_text(index, record_id=record_id, text=text, threshold=threshold, strategy=strategy)
        if match:
            duplicates.append({"duplicate_id": record_id, "kept_id": str(match["kept_id"]), "reason": str(match["reason"]), "score": round(float(match["score"]), 4)})
            continue
        kept_ids.append(record_id)
        add_to_similarity_index(index, record_id=record_id, text=text)
    return kept_ids, duplicates
