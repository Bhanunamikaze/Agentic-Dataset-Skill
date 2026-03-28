from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .base import build_bundle, build_relation, build_unit

_INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)[">]', re.MULTILINE)
_NAMESPACE_PATTERN = re.compile(r'^\s*namespace\s+([A-Za-z_]\w*)', re.MULTILINE)
_TYPE_PATTERN = re.compile(r'^\s*(class|struct|enum(?:\s+class)?)\s+([A-Za-z_]\w*)', re.MULTILINE)
_MACRO_PATTERN = re.compile(r'^\s*#\s*define\s+([A-Za-z_]\w*)', re.MULTILINE)
_TYPEDEF_PATTERN = re.compile(r'^\s*typedef\b.*?\b([A-Za-z_]\w*)\s*;', re.MULTILINE)
_FUNCTION_PATTERN = re.compile(
    r'^\s*(?!if\b|for\b|while\b|switch\b|catch\b|return\b)'
    r'(?:template\s*<[^>]+>\s*)?'
    r'(?:inline\s+|static\s+|constexpr\s+|virtual\s+|extern\s+|friend\s+|consteval\s+|constinit\s+)*'
    r'[\w:\<\>\~\*&\s]+\s+([A-Za-z_~]\w*(?:::\w+)*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:;|\{)',
    re.MULTILINE,
)
_ASM_PROC_PATTERN = re.compile(r'^\s*([A-Za-z_@?][\w@$?]*)\s+PROC\b', re.MULTILINE | re.IGNORECASE)
_ASM_LABEL_PATTERN = re.compile(r'^\s*([A-Za-z_@?][\w@$?]*)\s*:\s*(?:;.*)?$', re.MULTILINE)
_ASM_INCLUDE_PATTERN = re.compile(r'^\s*(?:INCLUDE|INCLUDELIB)\s+([^\s;]+)', re.MULTILINE | re.IGNORECASE)
_PROJECT_MEMBER_TAGS = {
    "ClCompile", "ClInclude", "None", "Text", "MASM", "CustomBuild", "CustomBuildStep"
}


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 17)].rstrip() + "\n...[truncated]"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_block_end(text: str, start_offset: int) -> int:
    brace_depth = 0
    seen_open = False
    for index in range(start_offset, len(text)):
        char = text[index]
        if char == "{":
            brace_depth += 1
            seen_open = True
        elif char == "}":
            if seen_open:
                brace_depth -= 1
                if brace_depth <= 0:
                    return index
    return min(len(text), start_offset + 1200)


def _extract_symbols(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    content = str(file_record.get("content") or "")
    source_path = str(file_record["source_path"])
    language = str(file_record.get("language") or "c_cpp")
    symbols: list[dict[str, Any]] = []

    def add_symbol(kind: str, name: str, start: int, end: int) -> None:
        snippet = content[start:end].strip()
        symbols.append(
            build_unit(
                kind=f"c_family_{kind}",
                source_path=source_path,
                title=name,
                language=language,
                content=_truncate(snippet, 1200),
                metadata={
                    "symbol_kind": kind,
                    "symbol_name": name,
                    "line_start": _line_number(content, start),
                    "line_end": _line_number(content, end),
                    "parser_mode": "heuristic",
                    "file_id": file_record["id"],
                },
                stable_payload={
                    "source_path": source_path,
                    "kind": kind,
                    "name": name,
                    "start": start,
                    "end": end,
                },
            )
        )

    for match in _NAMESPACE_PATTERN.finditer(content):
        add_symbol("namespace", match.group(1), match.start(), min(len(content), match.end() + 200))
    for match in _TYPE_PATTERN.finditer(content):
        add_symbol(match.group(1).replace(" ", "_"), match.group(2), match.start(), _find_block_end(content, match.start()))
    for match in _MACRO_PATTERN.finditer(content):
        add_symbol("macro", match.group(1), match.start(), min(len(content), match.end() + 160))
    for match in _TYPEDEF_PATTERN.finditer(content):
        add_symbol("typedef", match.group(1), match.start(), min(len(content), match.end() + 160))
    for match in _FUNCTION_PATTERN.finditer(content):
        add_symbol("function", match.group(1), match.start(), _find_block_end(content, match.start()))
    return symbols


def _extract_assembly_symbols(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    content = str(file_record.get("content") or "")
    source_path = str(file_record["source_path"])
    symbols: list[dict[str, Any]] = []

    def add_symbol(kind: str, name: str, start: int, end: int) -> None:
        symbols.append(
            build_unit(
                kind=f"assembly_{kind}",
                source_path=source_path,
                title=name,
                language="assembly",
                content=_truncate(content[start:end].strip(), 1200),
                metadata={
                    "symbol_kind": kind,
                    "symbol_name": name,
                    "line_start": _line_number(content, start),
                    "line_end": _line_number(content, end),
                    "parser_mode": "heuristic",
                    "file_id": file_record["id"],
                },
                stable_payload={
                    "source_path": source_path,
                    "kind": kind,
                    "name": name,
                    "start": start,
                    "end": end,
                },
            )
        )

    for match in _ASM_PROC_PATTERN.finditer(content):
        proc_name = match.group(1)
        end_match = re.search(rf'^\s*{re.escape(proc_name)}\s+ENDP\b', content[match.end():], re.MULTILINE | re.IGNORECASE)
        if end_match:
            end_offset = match.end() + end_match.end()
        else:
            end_offset = min(len(content), match.end() + 600)
        add_symbol("proc", proc_name, match.start(), end_offset)

    seen_labels: set[str] = {str(item["metadata"].get("symbol_name", "")).lower() for item in symbols}
    for match in _ASM_LABEL_PATTERN.finditer(content):
        label = match.group(1)
        if label.lower() in seen_labels:
            continue
        add_symbol("label", label, match.start(), min(len(content), match.end() + 200))
    return symbols


def _extract_includes(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    content = str(file_record.get("content") or "")
    includes: list[dict[str, Any]] = []
    is_assembly = str(file_record.get("kind")) in {"assembly_source", "assembly_include"}
    pattern = _ASM_INCLUDE_PATTERN if is_assembly else _INCLUDE_PATTERN
    for match in pattern.finditer(content):
        include_name = match.group(1 if is_assembly else 2).strip()
        includes.append(
            {
                "include": include_name,
                "delimiter": "" if is_assembly else match.group(1),
                "line": _line_number(content, match.start()),
                "syntax": "assembly" if is_assembly else "preprocessor",
            }
        )
    return includes


def _parse_solution_file(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    content = str(file_record.get("content") or "")
    solution_path = Path(file_record["source_path"])
    projects: list[dict[str, Any]] = []
    for match in re.finditer(
        r'Project\("(?P<project_type>[^"]+)"\)\s*=\s*"(?P<name>[^"]+)",\s*"(?P<path>[^"]+)",\s*"(?P<guid>[^"]+)"',
        content,
    ):
        project_path = (solution_path.parent / match.group("path")).resolve()
        projects.append(
            {
                "solution_path": str(solution_path),
                "project_name": match.group("name"),
                "project_path": str(project_path),
                "project_guid": match.group("guid"),
            }
        )
    return projects


def _parse_xml_file(path: str) -> ET.Element | None:
    try:
        return ET.fromstring(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_vcxproj_files(file_record: dict[str, Any]) -> dict[str, Any]:
    project_path = Path(file_record["source_path"])
    root = _parse_xml_file(str(project_path))
    project_name = project_path.stem
    includes: list[str] = []
    if root is None:
        return {
            "project_name": project_name,
            "project_path": str(project_path),
            "members": includes,
        }

    for node in root.iter():
        tag = _strip_namespace(node.tag)
        if tag not in _PROJECT_MEMBER_TAGS:
            continue
        include = node.attrib.get("Include")
        if not include:
            continue
        includes.append(str((project_path.parent / include).resolve()))

    return {
        "project_name": project_name,
        "project_path": str(project_path),
        "members": includes,
    }


def _parse_vcxproj_filters(file_record: dict[str, Any]) -> dict[str, str]:
    filters_path = Path(file_record["source_path"])
    root = _parse_xml_file(str(filters_path))
    if root is None:
        return {}
    filters: dict[str, str] = {}
    for node in root.iter():
        tag = _strip_namespace(node.tag)
        if tag not in _PROJECT_MEMBER_TAGS:
            continue
        include = node.attrib.get("Include")
        if not include:
            continue
        filter_text = ""
        for child in node:
            if _strip_namespace(child.tag) == "Filter" and child.text:
                filter_text = child.text.strip()
                break
        filters[str((filters_path.parent / include).resolve())] = filter_text
    return filters


def _resolve_include(
    include_name: str,
    source_path: str,
    files_by_path: dict[str, dict[str, Any]],
    files_by_name: dict[str, list[dict[str, Any]]],
) -> str | None:
    source_dir = Path(source_path).parent
    direct_candidate = str((source_dir / include_name).resolve())
    if direct_candidate in files_by_path:
        return direct_candidate

    base_name = Path(include_name).name.lower()
    candidates = files_by_name.get(base_name, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return str(candidates[0]["source_path"])

    same_dir = [
        str(item["source_path"]) for item in candidates
        if Path(item["source_path"]).parent == source_dir
    ]
    if same_dir:
        return same_dir[0]
    return str(candidates[0]["source_path"])


def _build_bundle_content(
    *,
    primary_file: dict[str, Any],
    related_files: list[dict[str, Any]],
    project_names: list[str],
    symbol_names: list[str],
    include_lines: list[str],
    bundle_max_chars: int,
) -> str:
    sections = [
        "Bundle Type: C/C++/Assembly source context",
        f"Primary File: {primary_file['source_path']}",
    ]
    if project_names:
        sections.append("Projects: " + ", ".join(project_names))
    sections.append("Related Files: " + ", ".join(str(item["source_path"]) for item in related_files))
    if symbol_names:
        sections.append("Detected Symbols: " + ", ".join(symbol_names[:20]))
    if include_lines:
        sections.append("Include Map:\n" + "\n".join(include_lines[:20]))

    remaining = max(bundle_max_chars - len("\n\n".join(sections)) - 64, 1200)
    excerpt_budget = max(600, remaining // max(1, len(related_files)))
    for item in related_files:
        excerpt = _truncate(str(item.get("content") or ""), excerpt_budget)
        sections.append(f"File: {item['source_path']}\n{excerpt}")

    content = "\n\n".join(section for section in sections if section.strip())
    return _truncate(content, bundle_max_chars)


def parse_c_family_corpus(
    files: list[dict[str, Any]],
    *,
    bundle_max_chars: int = 12000,
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    warnings: list[str] = []

    files_by_path = {str(item["source_path"]): item for item in files}
    files_by_name: dict[str, list[dict[str, Any]]] = {}
    for item in files:
        files_by_name.setdefault(Path(str(item["source_path"])).name.lower(), []).append(item)

    solution_entries: list[dict[str, Any]] = []
    project_memberships: dict[str, list[dict[str, Any]]] = {}
    project_filters: dict[str, dict[str, str]] = {}

    for item in files:
        kind = str(item["kind"])
        if kind == "visual_studio_solution":
            parsed_projects = _parse_solution_file(item)
            solution_entries.extend(parsed_projects)
            for project in parsed_projects:
                relations.append(
                    build_relation(
                        kind="solution_references_project",
                        source_path=str(item["source_path"]),
                        related_paths=[project["project_path"]],
                        metadata=project,
                        stable_payload=project,
                    )
                )
        elif kind == "visual_studio_project":
            project = _parse_vcxproj_files(item)
            for member_path in project["members"]:
                project_memberships.setdefault(member_path, []).append(project)
                relations.append(
                    build_relation(
                        kind="project_contains_file",
                        source_path=project["project_path"],
                        related_paths=[member_path],
                        metadata={
                            "project_name": project["project_name"],
                            "project_path": project["project_path"],
                            "member_path": member_path,
                        },
                        stable_payload={
                            "project_path": project["project_path"],
                            "member_path": member_path,
                        },
                    )
                )
        elif kind == "visual_studio_filters":
            project_filters[str(Path(item["source_path"]).with_suffix(""))] = _parse_vcxproj_filters(item)

    c_code_files = [
        item for item in files
        if str(item["kind"]) in {"c_source", "c_header", "assembly_source", "assembly_include"}
    ]

    includes_by_path: dict[str, list[dict[str, Any]]] = {}
    symbols_by_path: dict[str, list[dict[str, Any]]] = {}
    for item in c_code_files:
        if str(item["kind"]) in {"assembly_source", "assembly_include"}:
            symbols = _extract_assembly_symbols(item)
        else:
            symbols = _extract_symbols(item)
        symbols_by_path[str(item["source_path"])] = symbols
        units.extend(symbols)
        includes = _extract_includes(item)
        includes_by_path[str(item["source_path"])] = includes

        for include in includes:
            resolved_path = _resolve_include(
                include["include"],
                str(item["source_path"]),
                files_by_path,
                files_by_name,
            )
            metadata = {
                "include": include["include"],
                "delimiter": include["delimiter"],
                "line": include["line"],
                "resolved_path": resolved_path,
            }
            relations.append(
                build_relation(
                    kind="includes",
                    source_path=str(item["source_path"]),
                    related_paths=[resolved_path] if resolved_path else [],
                    metadata=metadata,
                    stable_payload={
                        "source_path": str(item["source_path"]),
                        "include": include["include"],
                        "resolved_path": resolved_path,
                    },
                )
            )
            if resolved_path is None:
                warnings.append(f"Unresolved include {include['include']} from {item['source_path']}")

    groups_by_stem: dict[str, list[dict[str, Any]]] = {}
    for item in c_code_files:
        key = Path(str(item["source_path"])).stem.lower()
        groups_by_stem.setdefault(key, []).append(item)

    processed: set[str] = set()
    for group_items in groups_by_stem.values():
        sorted_group = sorted(
            group_items,
            key=lambda item: (
                0 if str(item["kind"]) == "c_source" else
                1 if str(item["kind"]) == "c_header" else
                2 if str(item["kind"]) == "assembly_source" else
                3,
                str(item["source_path"]),
            ),
        )
        primary = sorted_group[0]
        primary_path = str(primary["source_path"])
        if primary_path in processed:
            continue

        related_map = {str(item["source_path"]): item for item in sorted_group}
        for item in sorted_group:
            path = str(item["source_path"])
            for include in includes_by_path.get(path, []):
                resolved_path = _resolve_include(
                    include["include"],
                    path,
                    files_by_path,
                    files_by_name,
                )
                if resolved_path and resolved_path in files_by_path and files_by_path[resolved_path]["kind"] in {"c_source", "c_header", "assembly_source", "assembly_include"}:
                    related_map.setdefault(resolved_path, files_by_path[resolved_path])
            processed.add(path)

        project_paths_for_group = {
            project["project_path"]
            for item in list(related_map.values())
            for project in project_memberships.get(str(item["source_path"]), [])
        }
        if project_paths_for_group:
            for candidate in c_code_files:
                candidate_path = str(candidate["source_path"])
                memberships = project_memberships.get(candidate_path, [])
                if not memberships:
                    continue
                if any(project["project_path"] in project_paths_for_group for project in memberships):
                    related_map.setdefault(candidate_path, candidate)
                    processed.add(candidate_path)

        related_files = list(related_map.values())
        related_files.sort(key=lambda item: str(item["source_path"]))
        for left in related_files:
            for right in related_files:
                if left["id"] >= right["id"]:
                    continue
                relations.append(
                    build_relation(
                        kind="companion_of",
                        source_path=str(left["source_path"]),
                        related_paths=[str(right["source_path"])],
                        metadata={
                            "left_kind": left["kind"],
                            "right_kind": right["kind"],
                        },
                        stable_payload={
                            "left": str(left["source_path"]),
                            "right": str(right["source_path"]),
                        },
                    )
                )

        project_info = {
            str(item["source_path"]): project_memberships.get(str(item["source_path"]), [])
            for item in related_files
        }
        project_names = sorted({
            project["project_name"]
            for projects in project_info.values()
            for project in projects
        })
        symbol_names = []
        for item in related_files:
            for symbol in symbols_by_path.get(str(item["source_path"]), []):
                name = str(symbol["metadata"].get("symbol_name") or "")
                if name:
                    symbol_names.append(name)

        include_lines = []
        for item in related_files:
            for include in includes_by_path.get(str(item["source_path"]), []):
                resolved_path = _resolve_include(
                    include["include"],
                    str(item["source_path"]),
                    files_by_path,
                    files_by_name,
                )
                display = include["include"]
                if resolved_path:
                    display = f"{include['include']} -> {resolved_path}"
                include_lines.append(f"{item['source_path']}:{include['line']} {display}")

        bundle_content = _build_bundle_content(
            primary_file=primary,
            related_files=related_files,
            project_names=project_names,
            symbol_names=symbol_names,
            include_lines=include_lines,
            bundle_max_chars=bundle_max_chars,
        )
        bundle = build_bundle(
            kind="c_family_context",
            source_path=primary_path,
            title=Path(primary_path).name,
            language="assembly" if str(primary.get("kind")) in {"assembly_source", "assembly_include"} else "c_cpp",
            content=bundle_content,
            related_paths=[str(item["source_path"]) for item in related_files],
            metadata={
                "primary_file": primary_path,
                "file_paths": [str(item["source_path"]) for item in related_files],
                "assembly_files": [
                    str(item["source_path"])
                    for item in related_files
                    if str(item["kind"]) in {"assembly_source", "assembly_include"}
                ],
                "project_names": project_names,
                "project_paths": sorted({
                    project["project_path"]
                    for projects in project_info.values()
                    for project in projects
                }),
                "symbol_names": sorted(dict.fromkeys(symbol_names)),
                "include_lines": include_lines[:50],
                "bundle_type": "code",
                "parser_mode": "heuristic",
                "filters": {
                    path: project_filters.get(str(Path(project["project_path"])), {}).get(path, "")
                    for path, projects in project_info.items()
                    for project in projects
                },
            },
            stable_payload={
                "primary_file": primary_path,
                "related_files": [str(item["source_path"]) for item in related_files],
            },
        )
        bundles.append(bundle)

    return {
        "units": units,
        "relations": relations,
        "bundles": bundles,
        "warnings": sorted(dict.fromkeys(warnings)),
    }
