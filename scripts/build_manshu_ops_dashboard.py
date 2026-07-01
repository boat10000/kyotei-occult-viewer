#!/usr/bin/env python3
"""Build the Manshu operations database and lightweight dashboard JSON.

This script does not change the production ranking logic. It reads the saved
daily JSON files, stores a normalized snapshot into SQLite, and writes a small
JSON summary that can be served by GitHub Pages.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
DEFAULT_DB = OUTPUT_DIR / "manshu_ops.sqlite"
DEFAULT_SUMMARY = OUTPUT_DIR / "manshu_ops_summary.json"

SOURCE_PATTERNS = [
    ("codex", "boaters_manshu_ranking_codex_*.json"),
    ("morning", "boaters_manshu_morning_ranking_*.json"),
    ("live", "boaters_manshu_live_ranking_*.json"),
    ("standard", "boaters_manshu_ranking_*.json"),
]

SOURCE_PRIORITY = {
    "codex": 40,
    "live": 30,
    "morning": 20,
    "standard": 10,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_combo(value: Any) -> str | None:
    if value is None:
        return None
    digits = [ch for ch in str(value) if ch.isdigit()]
    if len(digits) < 3:
        return None
    return "-".join(digits[:3])


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def display_time(value: Any) -> str:
    if not value:
        return "--:--"
    text = str(value)
    m = re.search(r"T(\d{2}:\d{2})", text)
    if m:
        return m.group(1)
    return text[-5:] if len(text) >= 5 else text


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def date_from_path(path: Path) -> str | None:
    m = re.search(r"(\d{8})", path.name)
    if not m:
        return None
    raw = m.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def result_of(race: dict[str, Any]) -> dict[str, Any]:
    res = race.get("result") or {}
    return {
        "trifecta": normalize_combo(res.get("trifecta") or res.get("combination")),
        "payout_yen": parse_int(res.get("payout_yen") or res.get("payout")),
        "manshu": bool(res.get("manshu")),
    }


def selection_of(race: dict[str, Any]) -> dict[str, Any]:
    sel = race.get("selection") or {}
    tickets = sel.get("tickets") or []
    normalized = [normalize_combo(t) for t in tickets]
    normalized = [t for t in normalized if t]
    return {
        "heads": sel.get("heads") or [],
        "axes": sel.get("axes") or [],
        "supports": sel.get("supports") or [],
        "keshi": sel.get("keshi"),
        "points": parse_int(sel.get("points")) or len(normalized),
        "tickets": normalized,
        "role_note": sel.get("role_note") or "",
        "keshi_reason": sel.get("keshi_reason") or "",
    }


def classify_decision(race: dict[str, Any]) -> str:
    rate = parse_float(race.get("manshu_rate_pct")) or 0.0
    decision = str(race.get("buy_decision") or "")
    alert_type = str(race.get("last_minute_alert_type") or "")
    checks = " / ".join(str(x) for x in (race.get("final_decision_checks") or []))

    if "強本命" in decision or "strong" in alert_type:
        return "強本命"
    if "本命" in decision or alert_type == "buy_ok" or rate >= 40.0:
        return "本命"
    if "準本命" in decision or 38.0 <= rate < 40.0:
        return "準本命"
    if "見送り" in decision:
        return "見送り"
    if "展示待ち" in decision or "展示" in checks:
        return "判定前"
    if alert_type == "late_riser":
        return "急浮上参考"
    return "未判定"


def iter_race_snapshots(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    for source_type, pattern in SOURCE_PATTERNS:
        for raw_path in sorted(glob.glob(str(output_dir / pattern))):
            path = Path(raw_path)
            if path in seen_files:
                continue
            seen_files.add(path)
            payload = load_json(path)
            if not payload:
                continue
            date_text = payload.get("date") or date_from_path(path)
            if not date_text:
                continue
            races = payload.get("strict_races") or payload.get("races") or []
            if not isinstance(races, list):
                continue
            for index, race in enumerate(races, start=1):
                if not isinstance(race, dict):
                    continue
                result = result_of(race)
                selection = selection_of(race)
                combo = result["trifecta"]
                ticket_set = set(selection["tickets"])
                ticket_hit = bool(combo and combo in ticket_set)
                metrics = race.get("metrics") or {}
                if not isinstance(metrics, dict):
                    metrics = {}
                rows.append(
                    {
                        "source_type": source_type,
                        "source_file": str(path.relative_to(ROOT)),
                        "source_priority": SOURCE_PRIORITY.get(source_type, 0),
                        "date": str(date_text),
                        "race_id": str(race.get("race_id") or f"{date_text}-{race.get('place_id')}-{race.get('round')}-{index}"),
                        "place_id": parse_int(race.get("place_id")),
                        "place_name": race.get("place_name") or "",
                        "round": parse_int(race.get("round")),
                        "deadline_time": race.get("deadline_time") or "",
                        "rank": parse_int(race.get("rank")) or index,
                        "race_grade": race.get("race_grade") or "",
                        "race_kind": race.get("race_kind") or "",
                        "series_title": race.get("series_title") or "",
                        "ranking_type": race.get("ranking_type") or "",
                        "manshu_rate_pct": parse_float(race.get("manshu_rate_pct")),
                        "base_manshu_rate_pct": parse_float(race.get("base_manshu_rate_pct")),
                        "buy_decision": race.get("buy_decision") or "",
                        "decision_class": classify_decision(race),
                        "alert_type": race.get("last_minute_alert_type") or "",
                        "condition": race.get("condition") or "",
                        "result_trifecta": combo or "",
                        "payout_yen": result["payout_yen"],
                        "is_manshu": bool(result["manshu"] or ((result["payout_yen"] or 0) >= 10000)),
                        "head_boats": ",".join(map(str, selection["heads"])),
                        "axis_boats": ",".join(map(str, selection["axes"])),
                        "support_boats": ",".join(map(str, selection["supports"])),
                        "keshi_boat": parse_int(selection["keshi"]),
                        "ticket_count": selection["points"],
                        "ticket_hit": ticket_hit,
                        "tickets_json": compact_json(selection["tickets"]),
                        "selection_json": compact_json(race.get("selection") or {}),
                        "metrics_json": compact_json(metrics),
                        "tenji_boats": parse_int(metrics.get("tenji_boats")),
                        "isshu_boats": parse_int(metrics.get("isshu_boats")),
                        "raw_isshu_boats": parse_int(metrics.get("raw_isshu_boats")),
                        "odds_snapshot_source": metrics.get("odds_snapshot_source") or "",
                        "created_at": now_iso(),
                    }
                )
    return rows


def boat_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = json.loads(snapshot["metrics_json"]) if snapshot.get("metrics_json") else {}
    boats = metrics.get("boats") or []
    out: list[dict[str, Any]] = []
    if not isinstance(boats, list):
        return out
    for boat in boats:
        if not isinstance(boat, dict):
            continue
        out.append(
            {
                "source_type": snapshot["source_type"],
                "date": snapshot["date"],
                "race_id": snapshot["race_id"],
                "boat_number": parse_int(boat.get("boat_number")),
                "composite_win_pct": parse_float(boat.get("composite_win_pct")),
                "composite_top3_pct": parse_float(boat.get("composite_top3_pct")),
                "ai_3ren_pct": parse_float(boat.get("top3_pct") or boat.get("ai_3ren_pct")),
                "general_3ren_pct": parse_float(boat.get("general_top3_pct")),
                "ai_plus": parse_float(boat.get("ai_plus")),
                "ai_plus_rank": parse_int(boat.get("ai_plus_rank")),
                "tenji_time": parse_float(boat.get("tenji_time")),
                "tenji_rank": parse_int(boat.get("tenji_rank")),
                "isshu_time": parse_float(boat.get("isshu_time")),
                "isshu_rank": parse_int(boat.get("isshu_rank")),
                "avg_isshu_diff": parse_float(boat.get("avg_isshu_diff")),
                "super_slit_alert": int(bool(boat.get("super_slit_alert"))),
                "matchup_label": boat.get("matchup_label") or "",
                "raw_json": compact_json(boat),
            }
        )
    return out


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        DROP TABLE IF EXISTS race_snapshots;
        DROP TABLE IF EXISTS boat_snapshots;
        CREATE TABLE race_snapshots (
          source_type TEXT NOT NULL,
          source_file TEXT NOT NULL,
          source_priority INTEGER NOT NULL,
          date TEXT NOT NULL,
          race_id TEXT NOT NULL,
          place_id INTEGER,
          place_name TEXT,
          round INTEGER,
          deadline_time TEXT,
          rank INTEGER,
          race_grade TEXT,
          race_kind TEXT,
          series_title TEXT,
          ranking_type TEXT,
          manshu_rate_pct REAL,
          base_manshu_rate_pct REAL,
          buy_decision TEXT,
          decision_class TEXT,
          alert_type TEXT,
          condition TEXT,
          result_trifecta TEXT,
          payout_yen INTEGER,
          is_manshu INTEGER,
          head_boats TEXT,
          axis_boats TEXT,
          support_boats TEXT,
          keshi_boat INTEGER,
          ticket_count INTEGER,
          ticket_hit INTEGER,
          tickets_json TEXT,
          selection_json TEXT,
          metrics_json TEXT,
          tenji_boats INTEGER,
          isshu_boats INTEGER,
          raw_isshu_boats INTEGER,
          odds_snapshot_source TEXT,
          created_at TEXT,
          PRIMARY KEY (source_type, date, race_id)
        );
        CREATE TABLE boat_snapshots (
          source_type TEXT NOT NULL,
          date TEXT NOT NULL,
          race_id TEXT NOT NULL,
          boat_number INTEGER NOT NULL,
          composite_win_pct REAL,
          composite_top3_pct REAL,
          ai_3ren_pct REAL,
          general_3ren_pct REAL,
          ai_plus REAL,
          ai_plus_rank INTEGER,
          tenji_time REAL,
          tenji_rank INTEGER,
          isshu_time REAL,
          isshu_rank INTEGER,
          avg_isshu_diff REAL,
          super_slit_alert INTEGER,
          matchup_label TEXT,
          raw_json TEXT,
          PRIMARY KEY (source_type, date, race_id, boat_number)
        );
        """
    )
    return con


def write_db(db_path: Path, snapshots: list[dict[str, Any]]) -> None:
    con = init_db(db_path)
    race_cols = [
        "source_type",
        "source_file",
        "source_priority",
        "date",
        "race_id",
        "place_id",
        "place_name",
        "round",
        "deadline_time",
        "rank",
        "race_grade",
        "race_kind",
        "series_title",
        "ranking_type",
        "manshu_rate_pct",
        "base_manshu_rate_pct",
        "buy_decision",
        "decision_class",
        "alert_type",
        "condition",
        "result_trifecta",
        "payout_yen",
        "is_manshu",
        "head_boats",
        "axis_boats",
        "support_boats",
        "keshi_boat",
        "ticket_count",
        "ticket_hit",
        "tickets_json",
        "selection_json",
        "metrics_json",
        "tenji_boats",
        "isshu_boats",
        "raw_isshu_boats",
        "odds_snapshot_source",
        "created_at",
    ]
    placeholders = ",".join("?" for _ in race_cols)
    con.executemany(
        f"INSERT OR REPLACE INTO race_snapshots ({','.join(race_cols)}) VALUES ({placeholders})",
        [[row.get(col) for col in race_cols] for row in snapshots],
    )
    boat_cols = [
        "source_type",
        "date",
        "race_id",
        "boat_number",
        "composite_win_pct",
        "composite_top3_pct",
        "ai_3ren_pct",
        "general_3ren_pct",
        "ai_plus",
        "ai_plus_rank",
        "tenji_time",
        "tenji_rank",
        "isshu_time",
        "isshu_rank",
        "avg_isshu_diff",
        "super_slit_alert",
        "matchup_label",
        "raw_json",
    ]
    boat_values: list[list[Any]] = []
    for snap in snapshots:
        for boat in boat_rows(snap):
            boat_values.append([boat.get(col) for col in boat_cols])
    con.executemany(
        f"INSERT OR REPLACE INTO boat_snapshots ({','.join(boat_cols)}) VALUES ({','.join('?' for _ in boat_cols)})",
        boat_values,
    )
    con.commit()
    con.close()


def primary_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["date"], row["race_id"])
        prev = chosen.get(key)
        if not prev or row["source_priority"] > prev["source_priority"]:
            chosen[key] = row
        elif prev and row["source_priority"] == prev["source_priority"]:
            # Prefer the snapshot with a result and more exhibition coverage.
            prev_score = int(prev.get("payout_yen") is not None) * 100 + (prev.get("tenji_boats") or 0)
            row_score = int(row.get("payout_yen") is not None) * 100 + (row.get("tenji_boats") or 0)
            if row_score > prev_score:
                chosen[key] = row
    return sorted(chosen.values(), key=lambda r: (r["date"], r.get("deadline_time") or "", r.get("rank") or 999))


def summarize_records(records: list[dict[str, Any]], name: str, pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    sub = [r for r in records if pred(r)]
    settled = [r for r in sub if r.get("payout_yen") is not None]
    bought = [r for r in settled if (r.get("ticket_count") or 0) > 0]
    stake = sum((r.get("ticket_count") or 0) * 100 for r in bought)
    payback = sum((r.get("payout_yen") or 0) for r in bought if r.get("ticket_hit"))
    hits = sum(1 for r in bought if r.get("ticket_hit"))
    manshu = sum(1 for r in settled if r.get("is_manshu"))
    manshu_hits = sum(1 for r in bought if r.get("ticket_hit") and r.get("is_manshu"))
    payouts = sorted((r.get("payout_yen") or 0) for r in settled if r.get("payout_yen") is not None)
    median_payout = None
    if payouts:
        mid = len(payouts) // 2
        median_payout = payouts[mid] if len(payouts) % 2 else round((payouts[mid - 1] + payouts[mid]) / 2)
    max_losing = 0
    cur = 0
    for r in bought:
        if r.get("ticket_hit"):
            cur = 0
        else:
            cur += 1
            max_losing = max(max_losing, cur)
    return {
        "segment": name,
        "races": len(sub),
        "settled_races": len(settled),
        "bought_races": len(bought),
        "manshu_count": manshu,
        "manshu_rate_pct": round(manshu / len(settled) * 100, 2) if settled else None,
        "ticket_hits": hits,
        "hit_rate_pct": round(hits / len(bought) * 100, 2) if bought else None,
        "manshu_ticket_hits": manshu_hits,
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": round(payback / stake * 100, 2) if stake else None,
        "avg_points": round(sum((r.get("ticket_count") or 0) for r in bought) / len(bought), 2) if bought else None,
        "median_payout_yen": median_payout,
        "max_payout_yen": max(payouts) if payouts else None,
        "max_losing_streak": max_losing,
    }


def grouped_summary(records: list[dict[str, Any]], group_key: str, limit: int = 20) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        key = str(r.get(group_key) or "不明")
        groups[key].append(r)
    out = []
    for key, rows in groups.items():
        item = summarize_records(rows, key, lambda _r: True)
        item[group_key] = key
        out.append(item)
    out.sort(key=lambda x: (-(x.get("settled_races") or 0), x.get(group_key) or ""))
    return out[:limit]


def latest_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"date": None, "races": []}
    latest_date = max(r["date"] for r in records)
    day = [r for r in records if r["date"] == latest_date]
    # For the daily view, prefer Codex top records; fall back to all primary records.
    codex_day = [r for r in day if r["source_type"] == "codex"]
    view_rows = codex_day or day
    view_rows = sorted(view_rows, key=lambda r: r.get("rank") or 999)[:10]
    return {
        "date": latest_date,
        "races": [
            {
                "rank": r.get("rank"),
                "place_name": r.get("place_name"),
                "round": r.get("round"),
                "deadline": display_time(r.get("deadline_time")),
                "manshu_rate_pct": r.get("manshu_rate_pct"),
                "decision_class": r.get("decision_class"),
                "buy_decision": r.get("buy_decision"),
                "heads": r.get("head_boats"),
                "axes": r.get("axis_boats"),
                "keshi": r.get("keshi_boat"),
                "ticket_count": r.get("ticket_count"),
                "ticket_hit": bool(r.get("ticket_hit")),
                "result_trifecta": r.get("result_trifecta"),
                "payout_yen": r.get("payout_yen"),
                "is_manshu": bool(r.get("is_manshu")),
            }
            for r in view_rows
        ],
    }


def build_summary(rows: list[dict[str, Any]], db_path: Path) -> dict[str, Any]:
    primary = primary_records(rows)
    segments = [
        ("全保存レース", lambda r: True),
        ("朝監視TOP10", lambda r: (r.get("rank") or 999) <= 10),
        ("展示後38%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0),
        ("準本命38-39.9", lambda r: 38.0 <= (r.get("manshu_rate_pct") or 0) < 40.0),
        ("本命40%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("強本命・買いOK", lambda r: r.get("decision_class") in {"強本命", "本命"} and (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("買い目あり", lambda r: (r.get("ticket_count") or 0) > 0),
    ]
    source_segments = [
        summarize_records([r for r in rows if r["source_type"] == source], f"source:{source}", lambda _r: True)
        for source, _pattern in SOURCE_PATTERNS
        if any(r["source_type"] == source for r in rows)
    ]
    return {
        "version": 1,
        "generated_at": now_iso(),
        "source": {
            "db_path": str(db_path.relative_to(ROOT)),
            "input_dir": str(OUTPUT_DIR.relative_to(ROOT)),
            "snapshot_count": len(rows),
            "primary_race_count": len(primary),
            "note": "保存済みJSONから作った運用検証用データです。本番ランキング生成ロジックは変更していません。",
        },
        "latest": latest_payload(primary),
        "segments": [summarize_records(primary, name, pred) for name, pred in segments],
        "source_segments": source_segments,
        "by_venue": grouped_summary(primary, "place_name", 24),
        "by_month": grouped_summary([{**r, "month": r["date"][:7]} for r in primary], "month", 36),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    db_path = Path(args.db)
    summary_path = Path(args.summary)
    rows = iter_race_snapshots(output_dir)
    write_db(db_path, rows)
    summary = build_summary(rows, db_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    print(f"wrote {db_path}")
    print(f"wrote {summary_path}")
    print(f"snapshots={len(rows)} primary={summary['source']['primary_race_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
