from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.files import write_json

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
WORKSPACE_DIR = ROOT_DIR / "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process draft batches through import, quality checks, coverage steering, and optional export."
    )
    parser.add_argument(
        "--batch",
        action="append",
        default=[],
        help="Path to a draft JSON/JSONL/CSV batch. Repeatable.",
    )
    parser.add_argument(
        "--batch-glob",
        action="append",
        default=[],
        help="Glob for draft batch files, e.g. 'workspace/drafts_batch_*.jsonl'. Repeatable.",
    )
    parser.add_argument(
        "--plan-file",
        help="Optional coverage plan consumed by scripts/coverage.py.",
    )
    parser.add_argument(
        "--source-type",
        default="generated",
        help="Source type for imported drafts.",
    )
    parser.add_argument(
        "--tool-context",
        default="generic",
        help="Originating tool context, for example codex, claude, or antigravity.",
    )
    parser.add_argument(
        "--user-query",
        default="dataset build loop",
        help="Description of the build session for run metadata.",
    )
    parser.add_argument(
        "--dedup-threshold",
        type=float,
        default=0.85,
        help="Similarity threshold used for import-time and incremental deduplication.",
    )
    parser.add_argument(
        "--review-file",
        help="Optional review file to promote heuristic passes to verified_pass during verify.",
    )
    parser.add_argument(
        "--verify-min-instruction-length",
        type=int,
        help="Optional override for verify.py --min-instruction-length.",
    )
    parser.add_argument(
        "--verify-min-response-length",
        type=int,
        help="Optional override for verify.py --min-response-length.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip verify.py and treat imported raw records as the active pool.",
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip incremental dedup.py after each batch.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Process every supplied batch even if the coverage plan is already satisfied.",
    )
    parser.add_argument(
        "--export-format",
        choices=("openai", "huggingface", "csv", "jsonl", "all"),
        help="Optional final export format.",
    )
    parser.add_argument(
        "--schema-file",
        help="Optional flat export schema for csv/jsonl export.",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional output directory for final export. Defaults to a unique workspace subdirectory.",
    )
    parser.add_argument(
        "--split",
        type=float,
        default=0.1,
        help="Holdout fraction for final export.",
    )
    parser.add_argument(
        "--coverage-group-by",
        action="append",
        default=[],
        help="Extra group-by field for coverage.py. Repeatable.",
    )
    parser.add_argument(
        "--db",
        help="SQLite path for this build loop. Defaults to a fresh workspace DB per invocation.",
    )
    parser.add_argument(
        "--report",
        help="Optional path to write the final JSON summary.",
    )
    return parser.parse_args()


def resolve_batches(args: argparse.Namespace) -> list[Path]:
    batch_paths = [Path(item).expanduser() for item in args.batch]
    for pattern in args.batch_glob:
        for match in sorted(glob.glob(pattern)):
            batch_paths.append(Path(match).expanduser())

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in batch_paths:
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        if not resolved.exists():
            raise SystemExit(f"Batch file not found: {resolved}")
        unique_paths.append(resolved)
        seen.add(key)
    if not unique_paths:
        raise SystemExit("Provide at least one --batch or --batch-glob input.")
    return unique_paths


def default_db_path(session_id: str) -> Path:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / f"build_loop_{session_id}.sqlite"


def default_output_dir(session_id: str) -> Path:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / f"build_exports_{session_id}"


def run_json_script(script_name: str, args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
    result = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        raise RuntimeError(f"{script_name} failed with exit code {result.returncode}\n{detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script_name} did not return valid JSON:\n{result.stdout}") from exc


def active_pool_statuses(*, skip_verify: bool, review_file: str | None) -> list[str]:
    if skip_verify:
        return ["raw_generated", "augmented"]
    if review_file:
        return ["verified_pass"]
    return ["judge_pending"]


def coverage_statuses(*, skip_verify: bool, review_file: str | None) -> list[str]:
    statuses = ["raw_generated", "augmented", "judge_pending", "verified_pass"]
    if skip_verify:
        return ["raw_generated", "augmented"]
    if review_file:
        return ["verified_pass"]
    return statuses


def build_generate_args(args: argparse.Namespace, batch_path: Path, db_path: Path) -> list[str]:
    return [
        "--input",
        str(batch_path),
        "--source-type",
        args.source_type,
        "--tool-context",
        args.tool_context,
        "--user-query",
        args.user_query,
        "--db",
        str(db_path),
        "--dedup-threshold",
        str(args.dedup_threshold),
    ]


def build_verify_args(args: argparse.Namespace, db_path: Path, source_run_id: str) -> list[str]:
    command = [
        "--from-status",
        "raw_generated",
        "--from-status",
        "augmented",
        "--source-run-id",
        source_run_id,
        "--tool-context",
        args.tool_context,
        "--user-query",
        args.user_query,
        "--source-type",
        args.source_type,
        "--db",
        str(db_path),
    ]
    if args.review_file:
        command.extend(["--review-file", args.review_file])
    if args.verify_min_instruction_length is not None:
        command.extend(["--min-instruction-length", str(args.verify_min_instruction_length)])
    if args.verify_min_response_length is not None:
        command.extend(["--min-response-length", str(args.verify_min_response_length)])
    return command


def build_dedup_args(args: argparse.Namespace, db_path: Path) -> list[str]:
    command = []
    for status in active_pool_statuses(skip_verify=args.skip_verify, review_file=args.review_file):
        command.extend(["--from-status", status])
    command.extend(
        [
            "--threshold",
            str(args.dedup_threshold),
            "--tool-context",
            args.tool_context,
            "--user-query",
            args.user_query,
            "--source-type",
            args.source_type,
            "--db",
            str(db_path),
        ]
    )
    return command


def build_coverage_args(args: argparse.Namespace, db_path: Path) -> list[str]:
    command: list[str] = []
    for status in coverage_statuses(skip_verify=args.skip_verify, review_file=args.review_file):
        command.extend(["--from-status", status])
    command.extend(
        [
            "--threshold",
            str(args.dedup_threshold),
            "--db",
            str(db_path),
        ]
    )
    if args.plan_file:
        command.extend(["--plan-file", args.plan_file])
    for field in args.coverage_group_by:
        command.extend(["--group-by", field])
    return command


def build_export_args(args: argparse.Namespace, db_path: Path, output_dir: Path) -> list[str]:
    command = [
        "--format",
        str(args.export_format),
        "--split",
        str(args.split),
        "--output-dir",
        str(output_dir),
        "--db",
        str(db_path),
    ]
    for status in active_pool_statuses(skip_verify=args.skip_verify, review_file=args.review_file):
        command.extend(["--from-status", status])
    if args.schema_file:
        command.extend(["--schema-file", args.schema_file])
    return command


def coverage_complete(coverage: dict[str, Any], *, plan_file: str | None) -> bool:
    if not plan_file:
        return False
    target_gap = coverage.get("target_effective_gap")
    target_satisfied = target_gap in (None, 0)
    return bool(
        target_satisfied
        and not coverage.get("coverage_gaps")
        and not coverage.get("mode_collapse")
        and not coverage.get("missing_metadata")
    )


def main() -> None:
    args = parse_args()
    session_id = f"build_{uuid.uuid4().hex[:12]}"
    batch_paths = resolve_batches(args)
    db_path = Path(args.db).expanduser().resolve() if args.db else default_db_path(session_id)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else default_output_dir(session_id)
    )

    summary: dict[str, Any] = {
        "session_id": session_id,
        "db_path": str(db_path),
        "batches_requested": [str(path) for path in batch_paths],
        "batches_processed": [],
        "skip_verify": args.skip_verify,
        "skip_dedup": args.skip_dedup,
        "review_file": args.review_file,
        "dedup_threshold": args.dedup_threshold,
        "plan_file": args.plan_file,
        "complete": False,
        "stop_reason": None,
        "final_coverage": None,
        "export": None,
    }

    for batch_path in batch_paths:
        batch_summary: dict[str, Any] = {
            "path": str(batch_path),
            "generate": run_json_script("generate.py", build_generate_args(args, batch_path, db_path)),
        }

        if not args.skip_verify:
            batch_summary["verify"] = run_json_script(
                "verify.py",
                build_verify_args(args, db_path, str(batch_summary["generate"]["run_id"])),
            )

        if not args.skip_dedup:
            batch_summary["dedup"] = run_json_script("dedup.py", build_dedup_args(args, db_path))

        batch_summary["coverage"] = run_json_script("coverage.py", build_coverage_args(args, db_path))
        summary["batches_processed"].append(batch_summary)
        summary["final_coverage"] = batch_summary["coverage"]
        summary["complete"] = coverage_complete(batch_summary["coverage"], plan_file=args.plan_file)

        if summary["complete"] and not args.keep_going:
            summary["stop_reason"] = "coverage_plan_satisfied"
            break

    if summary["stop_reason"] is None:
        summary["stop_reason"] = "all_batches_processed"

    if args.export_format:
        summary["export"] = run_json_script(
            "export.py",
            build_export_args(args, db_path, output_dir),
        )
        summary["export"]["output_dir"] = str(output_dir)

    if args.report:
        write_json(args.report, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
