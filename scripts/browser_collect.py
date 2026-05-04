from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __name__ == "__main__" or not getattr(sys.modules.get(__name__, None), "__package__", None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils.canonical import build_record_id
from scripts.utils.files import write_jsonl
from scripts.utils.web import chunk_text, extract_text

ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT_DIR / "workspace"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optional JavaScript-enabled URL collector using Playwright.")
    parser.add_argument("--urls", nargs="+", required=True, help="URLs to render and collect.")
    parser.add_argument("--output", help="Output JSONL path. Defaults to workspace/browser_collected_<timestamp>.jsonl")
    parser.add_argument("--max-chunk-chars", type=int, default=3000)
    parser.add_argument("--overlap-chars", type=int, default=200)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_record(url: str, title: str, chunk: str, index: int) -> dict[str, Any]:
    instruction = "Review this JavaScript-rendered source material and extract dataset-relevant evidence."
    record = {
        "task_type": "sft",
        "instruction": instruction,
        "context": title or url,
        "response": {"format": "single", "text": chunk},
        "metadata": {
            "difficulty": "unspecified",
            "persona": "general",
            "source_type": "url_reference",
            "source_origin": "real_world",
            "source_url": url,
            "source_title": title or url,
            "chunk_index": index,
            "collected_at": _utc_now(),
            "collection_mode": "browser_rendered_raw_material",
            "raw_material_only": True,
            "tags": [],
        },
        "pipeline_status": "pending",
        "status": "collected",
        "source_type": "url_reference",
        "source_uri": url,
    }
    record["id"] = build_record_id({"source_uri": url, "chunk_index": index, "browser": True})
    return record


async def collect(args: argparse.Namespace) -> list[dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Install optional browser dependencies with:\n"
            "  python3 -m pip install -r requirements-browser.txt\n"
            "  python3 -m playwright install chromium"
        ) from exc
    records: list[dict[str, Any]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        for url in args.urls:
            await page.goto(url, wait_until="networkidle", timeout=args.timeout_ms)
            html = await page.content()
            extracted = extract_text(html, url)
            title = await page.title() or extracted.title or url
            for index, chunk in enumerate(chunk_text(extracted.text, max_chars=args.max_chunk_chars, overlap=args.overlap_chars)):
                records.append(make_record(url, title, chunk, index))
        await browser.close()
    return records


def main() -> None:
    args = parse_args()
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output) if args.output else WORKSPACE_DIR / f"browser_collected_{timestamp}.jsonl"
    records = asyncio.run(collect(args))
    write_jsonl(output, records)
    print(json.dumps({"output": str(output), "records_collected": len(records), "warning": "Raw collected chunks only; draft canonical records before verify/export."}, indent=2))


if __name__ == "__main__":
    main()
