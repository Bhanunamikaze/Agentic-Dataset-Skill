from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd or ROOT_DIR),
        text=True,
        capture_output=True,
        check=True,
    )


class CanonicalNormalizationTests(unittest.TestCase):
    def test_normalizes_prompt_completion_into_sft_record(self) -> None:
        from scripts.utils.canonical import normalize_record

        record = normalize_record(
            {
                "prompt": "Explain shell quoting",
                "completion": "Use double quotes when interpolation is needed.",
                "difficulty": "medium",
                "persona": "mentor",
            }
        )

        self.assertEqual(record["task_type"], "sft")
        self.assertEqual(record["response"]["format"], "single")
        self.assertEqual(
            record["response"]["text"],
            "Use double quotes when interpolation is needed.",
        )
        self.assertEqual(record["metadata"]["difficulty"], "medium")
        self.assertEqual(record["metadata"]["persona"], "mentor")

    def test_normalizes_preference_pair_into_dpo_record(self) -> None:
        from scripts.utils.canonical import normalize_record

        record = normalize_record(
            {
                "instruction": "Rank two answers",
                "chosen": "Safe answer",
                "rejected": "Unsafe answer",
                "metadata": {"difficulty": "hard", "persona": "reviewer"},
            }
        )

        self.assertEqual(record["task_type"], "dpo")
        self.assertEqual(record["response"]["format"], "preference_pair")
        self.assertEqual(record["response"]["chosen"], "Safe answer")
        self.assertEqual(record["response"]["rejected"], "Unsafe answer")


class PipelineScriptTests(unittest.TestCase):
    def test_verify_dedup_and_export_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            db_path = temp_dir / "state.sqlite"
            input_path = temp_dir / "records.jsonl"
            review_path = temp_dir / "review.jsonl"
            schema_path = temp_dir / "custom_schema.json"
            output_dir = temp_dir / "exports"

            records = [
                {
                    "id": "sample_a",
                    "instruction": "Write a secure bash script skeleton",
                    "context": "Target POSIX shell environment",
                    "response": {
                        "format": "single",
                        "text": "Use set -euo pipefail, quote variables, and check exit codes.",
                    },
                    "metadata": {"difficulty": "medium", "persona": "devops"},
                    "pipeline_status": "pending",
                },
                {
                    "id": "sample_b",
                    "instruction": "Write a secure bash script skeleton",
                    "context": "Target POSIX shell environment",
                    "response": {
                        "format": "single",
                        "text": "Use set -euo pipefail, quote variables, and check exit codes.",
                    },
                    "metadata": {"difficulty": "medium", "persona": "devops"},
                    "pipeline_status": "pending",
                },
            ]
            reviews = [
                {"id": "sample_a", "score": 5, "reason": "Strong example.", "status": "pass"},
                {"id": "sample_b", "score": 5, "reason": "Duplicate but valid.", "status": "pass"},
            ]
            custom_schema = {
                "name": "test-export",
                "mode": "flat",
                "columns": [
                    {"name": "prompt", "source": "instruction"},
                    {"name": "answer", "source": "response.text"},
                    {"name": "persona", "source": "metadata.persona"},
                ],
            }

            input_path.write_text(
                "".join(json.dumps(item, ensure_ascii=True) + "\n" for item in records),
                encoding="utf-8",
            )
            review_path.write_text(
                "".join(json.dumps(item, ensure_ascii=True) + "\n" for item in reviews),
                encoding="utf-8",
            )
            schema_path.write_text(json.dumps(custom_schema, indent=2), encoding="utf-8")

            verify_result = run_script(
                "scripts/verify.py",
                "--input",
                str(input_path),
                "--review-file",
                str(review_path),
                "--db",
                str(db_path),
                "--tool-context",
                "codex",
            )
            verify_summary = json.loads(verify_result.stdout)
            self.assertEqual(verify_summary["verified_pass"], 2)

            dedup_result = run_script(
                "scripts/dedup.py",
                "--from-status",
                "verified_pass",
                "--db",
                str(db_path),
            )
            dedup_summary = json.loads(dedup_result.stdout)
            self.assertEqual(dedup_summary["duplicate_count"], 1)

            export_result = run_script(
                "scripts/export.py",
                "--format",
                "csv",
                "--schema-file",
                str(schema_path),
                "--split",
                "0.0",
                "--output-dir",
                str(output_dir),
                "--db",
                str(db_path),
            )
            export_summary = json.loads(export_result.stdout)
            self.assertEqual(export_summary["records_exported"], 1)
            self.assertTrue((output_dir / "dataset_train.csv").exists())
            self.assertTrue((output_dir / "DATA_CARD.md").exists())

            csv_lines = (output_dir / "dataset_train.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(csv_lines[0], "prompt,answer,persona")
            self.assertEqual(len(csv_lines), 2)

            connection = sqlite3.connect(db_path)
            try:
                statuses = {
                    row[0]: row[1]
                    for row in connection.execute(
                        "SELECT id, status FROM records ORDER BY id"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertEqual(statuses["sample_a"], "verified_pass")
            self.assertEqual(statuses["sample_b"], "deduped")


if __name__ == "__main__":
    unittest.main()
