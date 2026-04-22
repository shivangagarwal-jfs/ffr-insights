"""
Batch-generate summaries for all persona input files in data/.

Reads each data/<persona>/input.json, POSTs it to the local summary endpoint,
and writes the response to data/<persona>/output_summary.json.

Usage:
    python scripts/generate_summaries.py              # concurrent (default 4 workers)
    python scripts/generate_summaries.py --workers 8  # concurrent with 8 workers
    python scripts/generate_summaries.py --serial     # sequential, one at a time
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
SUMMARY_ENDPOINT = f"{BASE_URL}/v1/ffr_summary"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TIMEOUT = 120.0

DEFAULT_WORKERS = 4


async def generate_summary(
    client: httpx.AsyncClient, persona_dir: Path,
) -> tuple[str, dict | None, float]:
    """POST input.json and return (tag, response_dict | None, elapsed_seconds)."""
    tag = persona_dir.name
    input_file = persona_dir / "input.json"
    if not input_file.exists():
        return tag, None, 0.0

    payload = json.loads(input_file.read_text())
    t0 = time.perf_counter()
    resp = await client.post(SUMMARY_ENDPOINT, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    elapsed = time.perf_counter() - t0
    return tag, resp.json(), elapsed


def _process_result(
    persona_dir: Path,
    tag: str,
    data: dict | None,
    elapsed: float,
    results: dict[str, list[str]],
) -> None:
    if data is None:
        print(f"  SKIP  {tag}: no input.json")
        return
    out_file = persona_dir / "output_summary.json"
    out_file.write_text(json.dumps(data, indent=4, ensure_ascii=False))
    print(f"[{tag}] OK  ({elapsed:.1f}s) → {out_file}")
    results["ok"].append(tag)


async def main():
    parser = argparse.ArgumentParser(description="Batch-generate persona summaries")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Max concurrent requests (default {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--serial", action="store_true",
        help="Run sequentially instead of concurrently",
    )
    args = parser.parse_args()

    persona_dirs = sorted(
        p for p in DATA_DIR.iterdir() if p.is_dir() and (p / "input.json").exists()
    )
    if not persona_dirs:
        print("No persona directories with input.json found in", DATA_DIR)
        sys.exit(1)

    n = len(persona_dirs)
    names = [p.name for p in persona_dirs]
    print(f"Found {n} persona(s): {names}")

    results: dict[str, list[str]] = {"ok": [], "fail": []}
    wall_start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        if args.serial:
            print("Mode: serial\n")
            for persona_dir in persona_dirs:
                tag = persona_dir.name
                print(f"[{tag}] Generating summary …")
                try:
                    tag, data, elapsed = await generate_summary(client, persona_dir)
                    _process_result(persona_dir, tag, data, elapsed, results)
                except Exception as exc:
                    print(f"[{tag}] FAIL — {exc}")
                    results["fail"].append(tag)
        else:
            workers = min(args.workers, n)
            print(f"Mode: concurrent ({workers} workers)\n")
            semaphore = asyncio.Semaphore(workers)
            dir_by_tag = {p.name: p for p in persona_dirs}

            async def _limited(pd: Path) -> tuple[str, dict | None, float]:
                async with semaphore:
                    return await generate_summary(client, pd)

            gathered = await asyncio.gather(
                *(_limited(pd) for pd in persona_dirs),
                return_exceptions=True,
            )
            for persona_dir, outcome in zip(persona_dirs, gathered):
                tag = persona_dir.name
                if isinstance(outcome, Exception):
                    print(f"[{tag}] FAIL — {outcome}")
                    results["fail"].append(tag)
                else:
                    tag, data, elapsed = outcome
                    _process_result(dir_by_tag[tag], tag, data, elapsed, results)

    wall_elapsed = time.perf_counter() - wall_start
    print("\n--- Done ---")
    print(f"  Wall time: {wall_elapsed:.1f}s")
    print(f"  Success:   {len(results['ok'])}  {sorted(results['ok'])}")
    print(f"  Failed:    {len(results['fail'])}  {sorted(results['fail'])}")


if __name__ == "__main__":
    asyncio.run(main())
