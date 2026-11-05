"""Build/verify an offline historical Danish day-ahead price archive.

Uses the project's own price_data module so that the API schema, DST validation,
file names and cached-data format match the Streamlit application's loader.
Only COMPLETE months are archived. The tool is resumable and doesn't rewrite
valid existing archives unless --refresh is passed.

Examples:
  python scripts/update_price_archive.py --mode backfill --start-year 2016
  python scripts/update_price_archive.py --mode monthly
  python scripts/update_price_archive.py --mode check --start-year 2016
  python scripts/update_price_archive.py --mode backfill --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from price_data import (  # noqa: E402
    CHANGE_DATE,
    _cache_file,
    _chunk_period,
    _load_chunk,
    _validate_chunk,
)


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def previous_month(day: date) -> date:
    return (day - timedelta(days=1)).replace(day=1)


def requested_chunks(mode: str, start_year: int, as_of: date):
    """Unique yearly-hourly or monthly-quarterly chunks, no incomplete month."""
    completed_through = as_of.replace(day=1)
    cursor = (
        previous_month(completed_through)
        if mode == "monthly"
        else date(start_year, 1, 1)
    )
    seen = set()
    chunks = []

    while cursor < completed_through:
        dataset = "Elspotprices" if cursor < CHANGE_DATE else "DayAheadPrices"
        key = (dataset, cursor.year, None if dataset == "Elspotprices" else cursor.month)
        start, end = _chunk_period(dataset, cursor.year, cursor.month)
        if key not in seen and end <= completed_through:
            chunks.append((dataset, cursor.year, cursor.month, start, end))
            seen.add(key)
        cursor = next_month(cursor)

    return chunks


def validate_cached(dataset: str, area: str, year: int, month: int, start: date, end: date) -> bool:
    """Return False only if the file is absent; invalid files raise an error."""
    path = _cache_file(dataset, area, year, month)
    if not path.is_file():
        return False
    import pandas as pd
    data = pd.read_csv(path, dtype={"PriceArea": "string"})
    _validate_chunk(data, dataset, area, start, end)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validated DK1/DK2 day-ahead archive")
    parser.add_argument("--mode", choices=("backfill", "monthly", "check"), default="backfill")
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--area", choices=("both", "DK1", "DK2"), default="both")
    parser.add_argument("--delay", type=float, default=15.0, help="Pause between successful API downloads")
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--max-wait", type=int, default=600, help="Maximum accepted HTTP 429 wait in seconds")
    parser.add_argument("--max-new-files", type=int, default=0, help="0 downloads every missing file")
    parser.add_argument("--refresh", action="store_true", help="Re-download and replace existing files after validation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="Override today's date for reproducible testing")
    args = parser.parse_args(argv)

    if not 2010 <= args.start_year <= args.as_of.year:
        parser.error("--start-year must be between 2010 and the current year")
    if args.delay < 0 or args.max_retries < 0 or args.max_wait < 0 or args.max_new_files < 0:
        parser.error("Delay, retry and file limits must not be negative")
    if args.mode == "check" and args.refresh:
        parser.error("--refresh cannot be combined with --mode check")

    areas = ("DK1", "DK2") if args.area == "both" else (args.area,)
    batches = requested_chunks(args.mode, args.start_year, args.as_of)
    print(f"Archive mode={args.mode}; areas={','.join(areas)}; batches={len(batches)}; completed months only", flush=True)
    if args.mode != "monthly" and not batches:
        raise RuntimeError("No completed archival periods available")

    missing = 0
    present = 0
    downloaded = 0
    failed = 0
    requested_network = False

    for dataset, year, month, start, end in batches:
        for area in areas:
            path = _cache_file(dataset, area, year, month)
            label = f"{area}: {start} to {end} ({path.name})"
            try:
                exists = validate_cached(dataset, area, year, month, start, end)
            except (ValueError, KeyError, OSError) as exc:
                print(f"INVALID {label}: {exc}", flush=True)
                failed += 1
                continue

            if exists and not args.refresh:
                present += 1
                print(f"CACHED  {label}", flush=True)
                continue

            if args.mode == "check" or args.dry_run:
                missing += 1
                print(f"MISSING {label}" if not exists else f"REFRESH {label}", flush=True)
                continue

            if args.max_new_files and downloaded >= args.max_new_files:
                missing += 1
                print(f"PENDING {label}", flush=True)
                continue

            if requested_network and args.delay:
                time.sleep(args.delay)
            requested_network = True
            for attempt in range(args.max_retries + 1):
                try:
                    # The project's loader validates every interval and writes atomically.
                    # If refreshing, preserve the old archive until new data validate.
                    if exists and args.refresh:
                        import price_data
                        frame = price_data._fetch_remote(dataset, area, start, end)
                        price_data._validate_chunk(frame, dataset, area, start, end)
                        price_data._save_csv(frame, path)
                    else:
                        _load_chunk(dataset, area, year, month)
                    print(f"SAVED   {label}", flush=True)
                    downloaded += 1
                    break
                except RuntimeError as exc:
                    match = re.search(r"Vent\s+(\d+)\s+sekund", str(exc))
                    if not match or attempt == args.max_retries:
                        raise
                    delay = int(match.group(1)) + 3
                    if delay > args.max_wait:
                        raise RuntimeError(f"Rate limit requests waiting {delay}s (max {args.max_wait}s)") from exc
                    print(f"RATE LIMIT: waiting {delay}s before retry ({attempt + 1}/{args.max_retries})", flush=True)
                    time.sleep(delay)
                except Exception:
                    raise

    print(f"SUMMARY: validated={present}, downloaded={downloaded}, missing={missing}, invalid={failed}", flush=True)
    return 1 if failed or (args.mode == "check" and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
