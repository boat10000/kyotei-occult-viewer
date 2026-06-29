#!/usr/bin/env python3
"""Settle Codex core-focus forward validation logs with race results."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = "/Users/ohyabumasaya/Desktop/price_action_analysis/outputs/boaters_all_races.sqlite"
DEFAULT_LOG_DIR = ROOT / "data" / "output" / "forward_validation"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def norm_combo(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:3]


def fetch_result(con: sqlite3.Connection, entry: dict) -> dict | None:
    race_id = str(entry.get("race_id") or "")
    row = None
    if race_id:
        row = con.execute(
            """
            SELECT date, place_name, round, winning_number3t1, result_payout3t1
            FROM races
            WHERE race_id = ?
            """,
            (race_id,),
        ).fetchone()
    if row is None:
        row = con.execute(
            """
            SELECT date, place_name, round, winning_number3t1, result_payout3t1
            FROM races
            WHERE date = ? AND place_name = ? AND round = ?
            """,
            (entry.get("date"), entry.get("place_name"), entry.get("round")),
        ).fetchone()
    if row is None:
        return None
    date, place_name, round_no, trifecta, payout = row
    if trifecta is None or payout is None:
        return None
    return {
        "date": date,
        "place_name": place_name,
        "round": int(round_no) if round_no is not None else None,
        "trifecta": norm_combo(trifecta),
        "payout_yen": int(payout or 0),
    }


def settle_entry(entry: dict, result: dict) -> bool:
    tickets = {norm_combo(ticket) for ticket in entry.get("tickets") or []}
    tickets = {ticket for ticket in tickets if len(ticket) == 3}
    points = int(entry.get("points") or len(tickets))
    stake = points * 100
    trifecta = norm_combo(result.get("trifecta"))
    hit = bool(trifecta and trifecta in tickets)
    entry["status"] = "settled"
    entry["result"] = result
    entry["hit"] = hit
    entry["stake_yen"] = stake
    entry["payback_yen"] = int(result.get("payout_yen") or 0) if hit else 0
    entry["profit_yen"] = entry["payback_yen"] - stake
    entry["is_manshu"] = bool(hit and int(result.get("payout_yen") or 0) >= 10000)
    return hit


def summarize(entries: list[dict]) -> dict:
    settled = [entry for entry in entries if entry.get("status") == "settled"]
    stake = sum(int(entry.get("stake_yen") or 0) for entry in settled)
    payback = sum(int(entry.get("payback_yen") or 0) for entry in settled)
    hits = sum(1 for entry in settled if entry.get("hit"))
    manshu_hits = sum(1 for entry in settled if entry.get("is_manshu"))
    return {
        "entries": len(entries),
        "settled": len(settled),
        "pending": len(entries) - len(settled),
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": round(payback / stake * 100, 2) if stake else None,
        "hit_rate_pct": round(hits / len(settled) * 100, 2) if settled else None,
        "manshu_hit_rate_pct": round(manshu_hits / len(settled) * 100, 2) if settled else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="YYYY-MM-DD. Omit to process every log file.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if args.date:
        paths = [log_dir / f"core_focus_forward_{args.date.replace('-', '')}.json"]
    else:
        paths = sorted(log_dir.glob("core_focus_forward_*.json"))
    if not paths:
        print("no forward validation logs")
        return 0

    db_path = Path(args.db)
    updated = 0
    with sqlite3.connect(db_path) as con:
        for path in paths:
            payload = load_json(path, {})
            entries = payload.get("entries") or []
            changed = False
            for entry in entries:
                if entry.get("status") == "settled":
                    continue
                result = fetch_result(con, entry)
                if result is None:
                    continue
                settle_entry(entry, result)
                changed = True
                updated += 1
            if changed:
                payload["summary"] = summarize(entries)
                save_json(path, payload)
                print(f"settled {path}: {payload['summary']}")
    print(f"updated_entries={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
