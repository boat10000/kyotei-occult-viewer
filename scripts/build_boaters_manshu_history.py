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


def result_stats(rows: list[dict], top_n: int) -> dict:
    picked = rows[:top_n]
    settled = [row for row in picked if (row.get("result") or {}).get("payout_yen") is not None]
    hits = [row for row in settled if (row.get("result") or {}).get("manshu")]
    max_payout = max([(row.get("result") or {}).get("payout_yen") or 0 for row in settled], default=0)
    hit_labels = [
        {
            "rank": row.get("rank"),
            "race": f"{row.get('place_name')}{row.get('round')}R",
            "trifecta": (row.get("result") or {}).get("trifecta"),
            "payout_yen": (row.get("result") or {}).get("payout_yen"),
        }
        for row in hits
    ]
    return {
        "selected": len(picked),
        "settled": len(settled),
        "manshu_hits": len(hits),
        "manshu_rate_pct": round(len(hits) / len(settled) * 100, 2) if settled else None,
        "max_payout_yen": max_payout or None,
        "hit_races": hit_labels,
    }


def build_one(day: date, top_n: int, threshold: float) -> dict:
    date_text = day.isoformat()
    compact = day.strftime("%Y%m%d")
    rank_json = PRICE_OUT / f"manshu_daily_rank_{date_text}.json"
    rank_csv = PRICE_OUT / f"manshu_daily_rank_{date_text}.csv"
    rank_html = PRICE_OUT / "boaters_report" / f"manshu_daily_rank_{date_text}.html"
    public_json = PUBLIC_OUT / f"boaters_manshu_ranking_{compact}.json"
    codex_json = PUBLIC_OUT / f"boaters_manshu_ranking_codex_{compact}.json"

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

    payload_path = codex_json if codex_json.exists() else public_json
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    races = payload.get("races") or []
    strict_races = payload.get("strict_races") or []
    return {
        "date": date_text,
        "path": str(public_json.relative_to(ROOT)),
        "codex_path": str(codex_json.relative_to(ROOT)) if codex_json.exists() else str(public_json.relative_to(ROOT)),
        "logic_label": payload.get("logic_label"),
        "displayed_top_n": payload.get("summary", {}).get("displayed_top_n"),
        "settled_top_n": payload.get("summary", {}).get("settled_top_n"),
        "manshu_hits_top_n": payload.get("summary", {}).get("manshu_hits_top_n"),
        "actual_manshu_rate_top_n_pct": payload.get("summary", {}).get("actual_manshu_rate_top_n_pct"),
        "all_venue": {
            "top1": result_stats(races, 1),
            "top3": result_stats(races, 3),
            "top5": result_stats(races, 5),
            "top10": result_stats(races, top_n),
        },
        "strict": {
            "top10": result_stats(strict_races, min(top_n, len(strict_races))),
        },
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
    aggregate = {
        "all_venue": {
            "top1": aggregate_stats(summaries, "all_venue", "top1"),
            "top3": aggregate_stats(summaries, "all_venue", "top3"),
            "top5": aggregate_stats(summaries, "all_venue", "top5"),
            "top10": aggregate_stats(summaries, "all_venue", "top10"),
        },
        "strict": {
            "top10": aggregate_stats(summaries, "strict", "top10"),
        },
    }
    INDEX_OUT.write_text(
        json.dumps(
            {
                "version": "boaters-manshu-history-index-v2",
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "top_n": args.top_n,
                "threshold_pct": args.threshold,
                "logic_label": "Codex全場ランキング + 厳選ランキング",
                "aggregate": aggregate,
                "dates": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"dates": len(summaries), "index": str(INDEX_OUT)}, ensure_ascii=False))
    return 0


def aggregate_stats(summaries: list[dict], group: str, key: str) -> dict:
    selected = 0
    settled = 0
    hits = 0
    max_payout = 0
    hit_days = 0
    active_days = 0
    for item in summaries:
        stats = ((item.get(group) or {}).get(key) or {})
        if stats.get("selected"):
            active_days += 1
        selected += stats.get("selected") or 0
        settled += stats.get("settled") or 0
        hits += stats.get("manshu_hits") or 0
        max_payout = max(max_payout, stats.get("max_payout_yen") or 0)
        if stats.get("manshu_hits"):
            hit_days += 1
    return {
        "selected": selected,
        "settled": settled,
        "manshu_hits": hits,
        "manshu_rate_pct": round(hits / settled * 100, 2) if settled else None,
        "hit_days": hit_days,
        "days": active_days,
        "day_hit_rate_pct": round(hit_days / active_days * 100, 2) if active_days else None,
        "max_payout_yen": max_payout or None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
