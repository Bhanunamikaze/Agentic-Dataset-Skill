from __future__ import annotations

import ast as _ast
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
    text_by_id: dict[str, str] = field(default_factory=dict)
    minhash_by_id: dict[str, tuple[int, ...]] = field(default_factory=dict)


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


def tfidf_similarity(left: str, right: str) -> float:
    """Cosine similarity between token-count vectors of two texts."""
    return cosine_counts(Counter(tokenize(left)), Counter(tokenize(right)))


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def minhash_signature(tokens: set[str], *, num_perm: int = 64, seed: int = 0xC0DE) -> tuple[int, ...]:
    """Deterministic MinHash estimator of Jaccard similarity. num_perm=64 gives ~±0.06 error at 0.85 threshold."""
    if not tokens:
        return tuple(2**64 - 1 for _ in range(num_perm))
    sig = []
    token_bytes = [t.encode("utf-8") for t in tokens]
    for i in range(num_perm):
        perm_seed = (seed ^ (i * 2654435761)) & 0xFFFFFFFFFFFFFFFF
        min_hash = 2**64 - 1
        for tb in token_bytes:
            h = int.from_bytes(
                hashlib.blake2b(tb, digest_size=8, key=perm_seed.to_bytes(8, "big")).digest(),
                "big",
            )
            if h < min_hash:
                min_hash = h
        sig.append(min_hash)
    return tuple(sig)


def minhash_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a == b for a, b in zip(left, right)) / len(left)


def _near_score(
    *,
    strategy: str,
    text: str,
    shingles: set[str],
    kept_text: str,
    kept_tokens: set[str],
    minhash_sig: tuple[int, ...] | None = None,
    kept_minhash: tuple[int, ...] | None = None,
) -> float:
    if strategy == "minhash":
        if minhash_sig and kept_minhash:
            return minhash_similarity(minhash_sig, kept_minhash)
        return set_similarity(shingles, kept_tokens)  # fallback
    if strategy == "tfidf":
        return tfidf_similarity(text, kept_text)
    # shingle (default)
    return set_similarity(shingles, kept_tokens)


def add_to_similarity_index(index: SimilarityIndex, *, record_id: str, text: str) -> None:
    index.exact_seen[hash_text(text)] = record_id
    index.shingles_by_id[record_id] = shingle_set(text)
    index.text_by_id[record_id] = text
    index.minhash_by_id[record_id] = minhash_signature(shingle_set(text))


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
    minhash_sig = minhash_signature(shingles) if strategy == "minhash" else None
    best: dict[str, Any] | None = None
    for kept_id, kept_tokens in index.shingles_by_id.items():
        if kept_id == record_id:
            continue
        if strategy == "code":
            code_fp = code_fingerprint(text)
            kept_fp = code_fingerprint(index.text_by_id.get(kept_id, ""))
            score = 1.0 if code_fp and code_fp == kept_fp else set_similarity(shingles, kept_tokens)
            reason = "code_fingerprint" if score == 1.0 else "code_fallback_near"
        else:
            score = _near_score(
                strategy=strategy,
                text=text,
                shingles=shingles,
                kept_text=index.text_by_id.get(kept_id, ""),
                kept_tokens=kept_tokens,
                minhash_sig=minhash_sig,
                kept_minhash=index.minhash_by_id.get(kept_id),
            )
            reason = "minhash" if strategy == "minhash" else ("tfidf" if strategy == "tfidf" else "near")
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


def normalize_code_text(text: str) -> str:
    """Normalize Python code blocks for dedup: rename variables, strip comments.
    Non-Python content and invalid syntax are returned unchanged."""
    _PYTHON_BLOCK = re.compile(r"```(?:python|py)\s*(.*?)```", re.DOTALL | re.IGNORECASE)

    def _normalize_block(code: str) -> str:
        try:
            tree = _ast.parse(code)
        except SyntaxError:
            return code
        # Rename all Name nodes in source order
        names_seen: dict[str, str] = {}
        counter = 0
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Name) and node.id not in names_seen:
                names_seen[node.id] = f"var_{counter}"
                counter += 1

        class _Renamer(_ast.NodeTransformer):
            def visit_Name(self, node):
                node.id = names_seen.get(node.id, node.id)
                return node

            def visit_arg(self, node):
                node.arg = names_seen.get(node.arg, node.arg)
                return node

        renamed = _Renamer().visit(tree)
        try:
            return _ast.unparse(renamed)
        except Exception:
            return code

    def _replace(match):
        block = match.group(1).strip()
        normalized = _normalize_block(block)
        return f"```python\n{normalized}\n```"

    return _PYTHON_BLOCK.sub(_replace, text)
