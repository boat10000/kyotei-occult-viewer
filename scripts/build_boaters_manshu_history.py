#!/usr/bin/env python3
"""Build Codex BOATERS manshu ranking JSON files for a date range."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRICE_DIR = ROOT.parent / "price_action_analysis"
PRICE_OUT = PRICE_DIR / "outputs"
HISTORY_DB = PRICE_OUT / "boaters_all_races.sqlite"
RANK_SCRIPT = ROOT / "scripts" / "rank_daily_manshu_candidates.py"
SITE_DATA_SCRIPT = ROOT / "scripts" / "build_boaters_manshu_site_data.py"
PUBLIC_OUT = ROOT / "data" / "output"
INDEX_OUT = PUBLIC_OUT / "boaters_manshu_history_index.json"


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def run_cmd(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        result.check_returncode()


def build_one(day: date, top_n: int, threshold: float) -> dict:
    date_text = day.isoformat()
    compact = day.strftime("%Y%m%d")
    rank_json = PRICE_OUT / f"manshu_daily_rank_{date_text}.json"
    rank_csv = PRICE_OUT / f"manshu_daily_rank_{date_text}.csv"
    rank_html = PRICE_OUT / "boaters_report" / f"manshu_daily_rank_{date_text}.html"
    public_json = PUBLIC_OUT / f"boaters_manshu_ranking_{compact}.json"

    run_cmd(
        [
            sys.executable,
            str(RANK_SCRIPT),
            "--date",
            date_text,
            "--today-db",
            str(HISTORY_DB),
            "--history-db",
            str(HISTORY_DB),
            "--threshold",
            str(threshold),
            "--top-n",
            str(top_n),
            "--json-out",
            str(rank_json),
            "--csv-out",
            str(rank_csv),
            "--html-out",
            str(rank_html),
        ],
        PRICE_DIR,
    )

    run_cmd(
        [
            sys.executable,
            str(SITE_DATA_SCRIPT),
            "--source-json",
            str(rank_json),
            "--source-csv",
            str(rank_csv),
            "--out",
            str(public_json),
            "--top-n",
            str(top_n),
        ],
        ROOT,
    )

    payload = json.loads(public_json.read_text(encoding="utf-8"))
    return {
        "date": date_text,
        "path": str(public_json.relative_to(ROOT)),
        "displayed_top_n": payload.get("summary", {}).get("displayed_top_n"),
        "settled_top_n": payload.get("summary", {}).get("settled_top_n"),
        "manshu_hits_top_n": payload.get("summary", {}).get("manshu_hits_top_n"),
        "actual_manshu_rate_top_n_pct": payload.get("summary", {}).get("actual_manshu_rate_top_n_pct"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=27.0)
    args = parser.parse_args()

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if start > end:
        raise SystemExit("--start-date must be on or before --end-date")

    PUBLIC_OUT.mkdir(parents=True, exist_ok=True)
    summaries = [build_one(day, args.top_n, args.threshold) for day in daterange(start, end)]
    INDEX_OUT.write_text(
        json.dumps(
            {
                "version": "boaters-manshu-history-index-v1",
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "top_n": args.top_n,
                "threshold_pct": args.threshold,
                "dates": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"dates": len(summaries), "index": str(INDEX_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
