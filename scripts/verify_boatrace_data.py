#!/usr/bin/env python3
"""Small local checks for fetched and normalized BOAT RACE data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def normalize_date(value: str) -> str:
    return value.replace("-", "")


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def run(args: argparse.Namespace) -> int:
    date_compact = normalize_date(args.date)
    raw_dir = Path(args.raw_dir) / date_compact
    normalized_path = Path(args.normalized_dir) / f"{date_compact}.json"
    if not raw_dir.exists():
        return fail(f"raw directory missing: {raw_dir}")
    if not normalized_path.exists():
        return fail(f"normalized JSON missing: {normalized_path}")

    data = json.loads(normalized_path.read_text(encoding="utf-8"))
    venues = data.get("venues") or []
    if not venues:
        return fail("no venues parsed from official index")
    races = [race for venue in venues for race in venue.get("races", [])]
    if args.expect_race_data:
        if not races:
            return fail("no races parsed")
        six_boat_races = [race for race in races if len(race.get("boats") or []) == 6]
        if not six_boat_races:
            return fail("no racelist page yielded 6 boats")
    if args.expect_result:
        result_races = [race for race in races if (race.get("result") or {}).get("trifecta")]
        if not result_races:
            return fail("no trifecta result parsed")
        payout_races = [race for race in result_races if (race.get("result") or {}).get("payout_yen")]
        if not payout_races:
            return fail("no trifecta payout parsed")

    html_files = sorted(raw_dir.glob("*.html"))
    if not html_files:
        return fail("no raw HTML files saved")
    if any(re.search(r"Traceback|UnicodeDecodeError", path.read_text(encoding="utf-8", errors="replace")) for path in html_files):
        return fail("raw HTML contains an obvious Python error marker")

    print(
        "OK:",
        f"venues={len(venues)}",
        f"races={len(races)}",
        f"raw_html={len(html_files)}",
        f"normalized={normalized_path}",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--normalized-dir", default="data/normalized")
    parser.add_argument("--expect-race-data", action="store_true")
    parser.add_argument("--expect-result", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
