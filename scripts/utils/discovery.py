from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .artifacts import make_artifact
from .web import read_local_file

_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
})

_C_FAMILY_EXTENSIONS: frozenset[str] = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
})

_ASSEMBLY_EXTENSIONS: frozenset[str] = frozenset({
    ".asm", ".s", ".asmx",
})

_ASSEMBLY_INCLUDE_EXTENSIONS: frozenset[str] = frozenset({
    ".inc",
})

_ARTICLE_EXTENSIONS: frozenset[str] = frozenset({
    ".html", ".htm", ".mhtml", ".md", ".txt",
})

_PROJECT_FILES: frozenset[str] = frozenset({
    ".sln", ".vcxproj", ".vcxproj.filters",
})


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def classify_source_path(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    name = candidate.name.lower()

    if name.endswith(".vcxproj.filters"):
        return {
            "supported": True,
            "file_kind": "visual_studio_filters",
            "language": "xml",
            "parser_key": "c_family",
        }
    if suffix == ".sln":
        return {
            "supported": True,
            "file_kind": "visual_studio_solution",
            "language": "plaintext",
            "parser_key": "c_family",
        }
    if suffix == ".vcxproj":
        return {
            "supported": True,
            "file_kind": "visual_studio_project",
            "language": "xml",
            "parser_key": "c_family",
        }
    if suffix in _C_FAMILY_EXTENSIONS:
        return {
            "supported": True,
            "file_kind": "c_header" if suffix in {".h", ".hh", ".hpp", ".hxx", ".inl"} else "c_source",
            "language": "c_cpp",
            "parser_key": "c_family",
        }
    if suffix in _ASSEMBLY_EXTENSIONS:
        return {
            "supported": True,
            "file_kind": "assembly_source",
            "language": "assembly",
            "parser_key": "c_family",
        }
    if suffix in _ASSEMBLY_INCLUDE_EXTENSIONS:
        return {
            "supported": True,
            "file_kind": "assembly_include",
            "language": "assembly",
            "parser_key": "c_family",
        }
    if suffix in {".html", ".htm"}:
        return {
            "supported": True,
            "file_kind": "html_document",
            "language": "html",
            "parser_key": "article",
        }
    if suffix == ".mhtml":
        return {
            "supported": True,
            "file_kind": "mhtml_document",
            "language": "mhtml",
            "parser_key": "article",
        }
    if suffix == ".md":
        return {
            "supported": True,
            "file_kind": "markdown_document",
            "language": "markdown",
            "parser_key": "article",
        }
    if suffix == ".txt":
        return {
            "supported": True,
            "file_kind": "text_document",
            "language": "text",
            "parser_key": "article",
        }
    return {
        "supported": False,
        "file_kind": "unsupported",
        "language": None,
        "parser_key": None,
    }


def _iter_candidate_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]

    files: list[Path] = []
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file():
            continue
        if any(part in _SKIP_DIRS for part in candidate.parts):
            continue
        files.append(candidate)
    return files


def discover_source_files(
    paths: list[str],
    *,
    max_files: int = 500,
) -> dict[str, Any]:
    discovered: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    roots: list[str] = []

    for raw_path in paths:
        root = Path(raw_path).resolve()
        if not root.exists():
            skipped.append({"path": str(root), "reason": "missing"})
            continue
        roots.append(str(root))
        for candidate in _iter_candidate_files(root):
            classification = classify_source_path(candidate)
            if not classification["supported"]:
                continue
            try:
                content = read_local_file(candidate)
            except Exception as exc:
                skipped.append({"path": str(candidate), "reason": f"read_error:{exc}"})
                continue

            relative_path = candidate.name
            if root.is_dir():
                relative_path = str(candidate.relative_to(root))

            discovered.append(
                make_artifact(
                    artifact_type="file",
                    kind=str(classification["file_kind"]),
                    source_path=str(candidate),
                    title=candidate.name,
                    language=classification["language"],
                    content=content,
                    metadata={
                        "root_path": str(root),
                        "relative_path": relative_path,
                        "extension": candidate.suffix.lower(),
                        "parser_key": classification["parser_key"],
                        "sha256": sha256_text(content),
                        "size_bytes": candidate.stat().st_size,
                        "project_descriptor": candidate.suffix.lower() in _PROJECT_FILES
                        or candidate.name.lower().endswith(".vcxproj.filters"),
                    },
                    stable_payload={
                        "source_path": str(candidate),
                        "sha256": sha256_text(content),
                    },
                )
            )
            if len(discovered) >= max_files:
                break
        if len(discovered) >= max_files:
            break

    return {
        "roots": roots,
        "files": discovered,
        "skipped": skipped,
    }
