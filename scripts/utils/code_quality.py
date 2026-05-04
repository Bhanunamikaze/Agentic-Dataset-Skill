from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any, Mapping

FENCE_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_+.#-]*)\s*(?P<body>.*?)```", re.DOTALL)


def primary_response_text(record: Mapping[str, Any]) -> str:
    response = record.get("response") or {}
    if isinstance(response, Mapping) and response.get("format") == "preference_pair":
        return "\n\n".join(part for part in [str(response.get("chosen") or ""), str(response.get("rejected") or "")] if part)
    if isinstance(response, Mapping):
        return str(response.get("text") or "")
    return str(response or "")


def extract_fenced_blocks(text: str) -> list[dict[str, str]]:
    return [
        {"language": (m.group("lang") or "").strip().lower(), "code": m.group("body").strip()}
        for m in FENCE_PATTERN.finditer(text or "")
    ]


def _balanced_quotes(text: str, quote: str) -> bool:
    escaped = False
    count = 0
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            count += 1
    return count % 2 == 0


def _balanced_pairs(text: str, pairs: tuple[tuple[str, str], ...]) -> bool:
    for left, right in pairs:
        depth = 0
        for char in text:
            if char == left:
                depth += 1
            elif char == right:
                depth -= 1
            if depth < 0:
                return False
        if depth != 0:
            return False
    return True


class _NormalizePythonAst(ast.NodeTransformer):
    """Normalize identifiers/literals so equivalent Python snippets fingerprint similarly."""

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802 - ast API
        return ast.copy_location(ast.Name(id="VAR", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:  # noqa: N802 - ast API
        node.arg = "ARG"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802 - ast API
        if isinstance(node.value, str):
            value: Any = "STR"
        elif isinstance(node.value, (int, float, complex)):
            value = "NUM"
        else:
            value = node.value
        return ast.copy_location(ast.Constant(value=value), node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802 - ast API
        node.name = "FUNC"
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # noqa: N802 - ast API
        node.name = "FUNC"
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # noqa: N802 - ast API
        node.name = "CLASS"
        return self.generic_visit(node)


def python_ast_fingerprint(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    normalized = _NormalizePythonAst().visit(tree)
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, annotate_fields=True, include_attributes=False)


def code_fingerprint(text: str) -> str:
    parts: list[str] = []
    for block in extract_fenced_blocks(text):
        language = block["language"]
        code = block["code"]
        if language in {"python", "py"}:
            fingerprint = python_ast_fingerprint(code)
            if fingerprint:
                parts.append("python_ast:" + fingerprint)
                continue
        normalized = re.sub(r"\s+", " ", code.strip().lower())
        if normalized:
            parts.append(f"{language or 'code'}:{normalized}")
    if not parts:
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        parts.append(normalized)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def code_quality_errors(record: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    config = plan.get("code_quality") or {}
    if not isinstance(config, Mapping) or not config.get("enabled"):
        return []
    text = primary_response_text(record)
    instruction = str(record.get("instruction") or "").lower()
    blocks = extract_fenced_blocks(text)
    errors: list[str] = []
    json_expected = bool(config.get("json") or "valid json" in instruction or "return only json" in instruction)
    python_expected = bool(config.get("python_ast") or "python" in instruction)
    if json_expected:
        json_blocks = [b for b in blocks if b["language"] == "json"]
        targets = [b["code"] for b in json_blocks] or [text]
        for index, payload in enumerate(targets, start=1):
            try:
                json.loads(payload)
            except json.JSONDecodeError as exc:
                errors.append(f"json syntax error in target {index}: {exc.msg}")
    if python_expected:
        py_blocks = [b for b in blocks if b["language"] in {"python", "py"}]
        for index, block in enumerate(py_blocks, start=1):
            try:
                ast.parse(block["code"])
            except SyntaxError as exc:
                errors.append(f"python AST syntax error in block {index}: {exc.msg}")
    if config.get("javascript_balance"):
        for index, block in enumerate([b for b in blocks if b["language"] in {"js", "javascript", "ts", "typescript"}], start=1):
            if not _balanced_pairs(block["code"], (("(", ")"), ("[", "]"), ("{", "}"))) or not _balanced_quotes(block["code"], '"') or not _balanced_quotes(block["code"], "'"):
                errors.append(f"javascript/typescript balance error in block {index}")
    if config.get("shell_balance"):
        for index, block in enumerate([b for b in blocks if b["language"] in {"bash", "sh", "shell", "zsh"}], start=1):
            if not _balanced_quotes(block["code"], '"') or not _balanced_quotes(block["code"], "'"):
                errors.append(f"shell quote balance error in block {index}")
    if config.get("sql_balance"):
        for index, block in enumerate([b for b in blocks if b["language"] == "sql"], start=1):
            if not _balanced_pairs(block["code"], (("(", ")"),)) or not _balanced_quotes(block["code"], "'"):
                errors.append(f"sql balance error in block {index}")
    return errors
