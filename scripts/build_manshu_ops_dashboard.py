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


def combo_key(value: Any) -> str | None:
    normalized = normalize_combo(value)
    return normalized.replace("-", "") if normalized else None


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


def ints_from_csv(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,\s]+", str(value))
    out: list[int] = []
    for item in raw:
        n = parse_int(item)
        if n and 1 <= n <= 6 and n not in out:
            out.append(n)
    return out


def read_json_field(row: dict[str, Any], key: str, default: Any) -> Any:
    try:
        value = json.loads(row.get(key) or "")
    except Exception:
        return default
    return value if value is not None else default


def metrics_boats(row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = read_json_field(row, "metrics_json", {})
    boats = metrics.get("boats") if isinstance(metrics, dict) else []
    if not isinstance(boats, list):
        return []
    return [boat for boat in boats if isinstance(boat, dict)]


def boat_number(boat: dict[str, Any]) -> int | None:
    n = parse_int(boat.get("boat_number"))
    return n if n and 1 <= n <= 6 else None


def ai_plus_score(boat: dict[str, Any]) -> float | None:
    explicit = parse_float(boat.get("ai_plus"))
    if explicit is not None:
        return explicit
    ai = parse_float(boat.get("top3_pct") or boat.get("ai_3ren_pct"))
    general = parse_float(boat.get("general_top3_pct"))
    if ai is not None or general is not None:
        return (ai or 0.0) + (general or 0.0)
    return parse_float(boat.get("three_ren_pct") or boat.get("composite_top3_pct"))


def sorted_boats_by(row: dict[str, Any], score_func: Callable[[dict[str, Any]], float | None], allowed: set[int] | None = None) -> list[int]:
    scored: list[tuple[float, int]] = []
    for boat in metrics_boats(row):
        n = boat_number(boat)
        if not n or (allowed is not None and n not in allowed):
            continue
        score = score_func(boat)
        if score is None:
            continue
        scored.append((score, n))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _score, n in scored]


def dedupe(values: list[int]) -> list[int]:
    out: list[int] = []
    for value in values:
        if value and 1 <= value <= 6 and value not in out:
            out.append(value)
    return out


def current_selection(row: dict[str, Any]) -> dict[str, Any]:
    selection = read_json_field(row, "selection_json", {})
    if not isinstance(selection, dict):
        selection = {}
    return selection


def fallback_heads(row: dict[str, Any], allowed: set[int] | None = None, count: int = 2) -> list[int]:
    heads = ints_from_csv(row.get("head_boats"))
    if allowed is not None:
        heads = [h for h in heads if h in allowed]
    ranked = sorted_boats_by(row, lambda b: parse_float(b.get("composite_win_pct")), allowed=allowed)
    return dedupe(heads + ranked + ([3, 4, 5, 6] if allowed == {3, 4, 5, 6} else [1, 2, 3, 4, 5, 6]))[:count]


def fallback_axes(row: dict[str, Any], count: int = 2, rank_start: int = 0) -> list[int]:
    axes = ints_from_csv(row.get("axis_boats"))
    ranked = sorted_boats_by(row, ai_plus_score)
    combined = dedupe(ranked + axes + [1, 2, 3, 4, 5, 6])
    return combined[rank_start : rank_start + count]


def fallback_keshi(row: dict[str, Any]) -> int:
    n = parse_int(row.get("keshi_boat"))
    if n and 1 <= n <= 6:
        return n
    scored: list[tuple[float, int]] = []
    for boat in metrics_boats(row):
        boat_no = boat_number(boat)
        score = ai_plus_score(boat)
        if boat_no and score is not None:
            scored.append((score, boat_no))
    if scored:
        scored.sort(key=lambda x: (x[0], x[1]))
        return scored[0][1]
    return 6


def limit_unique(tickets: list[str], max_points: int) -> list[str]:
    out: list[str] = []
    for ticket in tickets:
        key = combo_key(ticket)
        if not key or len(set(key)) != 3:
            continue
        normalized = "-".join(key)
        if normalized not in out:
            out.append(normalized)
        if len(out) >= max_points:
            break
    return out


def formation_tickets(heads: list[int], axes: list[int], supports: list[int], max_points: int = 15) -> list[str]:
    tickets: list[str] = []
    heads = dedupe(heads)
    axes = dedupe(axes)
    supports = dedupe(supports)
    for head in heads:
        for axis in axes:
            if axis == head:
                continue
            for support in supports:
                if support in {head, axis}:
                    continue
                tickets.append(f"{head}-{axis}-{support}")
                tickets.append(f"{head}-{support}-{axis}")
    return limit_unique(tickets, max_points)


def filter_value_tickets(
    tickets: list[str],
    *,
    require_56: bool = False,
    no_1_head: bool = False,
    first_outer_or_56: bool = False,
    max_points: int = 12,
) -> list[str]:
    filtered: list[str] = []
    for ticket in tickets:
        key = combo_key(ticket)
        if not key:
            continue
        nums = [parse_int(ch) for ch in key]
        if any(n is None for n in nums):
            continue
        first = nums[0]
        has_56 = 5 in nums or 6 in nums
        if require_56 and not has_56:
            continue
        if no_1_head and first == 1:
            continue
        if first_outer_or_56 and not ((first or 0) >= 3 or has_56):
            continue
        filtered.append("-".join(str(n) for n in nums if n is not None))
    return limit_unique(filtered, max_points)


def non1_composite_heads(row: dict[str, Any], count: int = 2) -> list[int]:
    return sorted_boats_by(row, lambda b: parse_float(b.get("composite_win_pct")), allowed={2, 3, 4, 5, 6})[:count]


def ai13_axes(row: dict[str, Any]) -> list[int]:
    ranked = fallback_axes(row, 3, rank_start=0)
    if len(ranked) >= 3:
        return dedupe([ranked[0], ranked[2]])
    return ranked


def box_tickets(boats: list[int]) -> list[str]:
    boats = dedupe(boats)[:3]
    tickets: list[str] = []
    for first in boats:
        for second in boats:
            for third in boats:
                if len({first, second, third}) == 3:
                    tickets.append(f"{first}-{second}-{third}")
    return limit_unique(tickets, 6)


def strategy_tickets(row: dict[str, Any], strategy_id: str) -> list[str]:
    selection = current_selection(row)
    saved = [t for t in (selection.get("tickets") or []) if combo_key(t)]
    heads = fallback_heads(row, count=2)
    outer_heads = fallback_heads(row, allowed={3, 4, 5, 6}, count=2)
    ai_heads = head_candidates(row, "ai_plus_top2", 2)
    hybrid_heads = head_candidates(row, "honmei_hybrid_v1", 2)
    axes_current = dedupe(ints_from_csv(row.get("axis_boats")) + fallback_axes(row, 2))[:2]
    axes_ai23 = fallback_axes(row, 2, rank_start=1)
    axes_ai13 = dedupe(ai13_axes(row) + axes_ai23)[:2]
    axis_ai2 = fallback_axes(row, 1, rank_start=1)
    axis_ai3 = fallback_axes(row, 1, rank_start=2)
    keshi = fallback_keshi(row)
    supports = [n for n in range(1, 7) if n != keshi]
    supports_no1 = [n for n in range(2, 7) if n != keshi]

    if strategy_id == "saved_current":
        return limit_unique(saved, 30)
    if strategy_id == "head2_axis2_current_15":
        return formation_tickets(heads, axes_current, supports, 15)
    if strategy_id == "head1_axis2_current":
        return formation_tickets(heads[:1], axes_current, supports, 10)
    if strategy_id == "head2_axis1_current":
        return formation_tickets(heads, axes_current[:1], supports, 10)
    if strategy_id == "outer_head2_ai23_12":
        return formation_tickets(outer_heads, axes_ai23, supports, 12)
    if strategy_id == "outer_head2_ai3_8":
        return formation_tickets(outer_heads, axis_ai3, supports, 8)
    if strategy_id == "outer_head2_no1_ai23_12":
        axes = [a for a in axes_ai23 if a != 1] or axis_ai2
        return formation_tickets(outer_heads, axes, supports_no1, 12)
    if strategy_id == "odds_b1_fade_comp_ai13_12":
        if not popular_b1_overbet_danger(row):
            return []
        return formation_tickets(non1_composite_heads(row, 2), axes_ai13, supports, 12)
    if strategy_id == "odds_gap_b1_fade_strong_12":
        if not popular_b1_overbet_strong(row):
            return []
        return formation_tickets(non1_composite_heads(row, 2), axes_ai13, supports, 12)
    if strategy_id == "odds_gap_b1_fade_filtered_12":
        if not popular_b1_overbet_filtered(row):
            return []
        return formation_tickets(non1_composite_heads(row, 2), axes_ai13, supports, 12)
    if strategy_id == "value_ai_head2_ai23_has56_12":
        if not any(h in {5, 6} for h in hybrid_heads):
            return []
        tickets = formation_tickets(ai_heads, axes_ai23, supports, 30)
        return filter_value_tickets(tickets, require_56=True, max_points=12)
    if strategy_id == "value_ai_head2_ai23_no1head56_12":
        if not any(h in {5, 6} for h in hybrid_heads):
            return []
        tickets = formation_tickets(ai_heads, axes_ai23, supports, 30)
        return filter_value_tickets(tickets, require_56=True, no_1_head=True, max_points=12)
    if strategy_id == "value_hybrid_head2_ai23_has56_12":
        if not any(h in {5, 6} for h in hybrid_heads):
            return []
        tickets = formation_tickets(hybrid_heads, axes_ai23, supports, 30)
        return filter_value_tickets(tickets, require_56=True, max_points=12)
    if strategy_id == "value_comp_ai13_outer_or_56_12":
        tickets = formation_tickets(heads, axes_ai13, supports, 30)
        return filter_value_tickets(tickets, first_outer_or_56=True, max_points=12)
    if strategy_id == "three_boat_box":
        return box_tickets(dedupe(outer_heads + axes_current + fallback_axes(row, 2)))
    if strategy_id == "outer3_boat_box":
        return box_tickets(dedupe(outer_heads + sorted_boats_by(row, lambda b: parse_float(b.get("composite_top3_pct")), allowed={3, 4, 5, 6})))
    return []


VALUE_BUY_PRIMARY_STRATEGY = "odds_gap_b1_fade_strong_12"
VALUE_BUY_FILTERED_STRATEGY = "odds_gap_b1_fade_filtered_12"
VALUE_BUY_SECONDARY_STRATEGY = "odds_b1_fade_comp_ai13_12"
VALUE_BUY_FALLBACK_STRATEGY = "value_ai_head2_ai23_has56_12"


def value_buy_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    rate = row.get("manshu_rate_pct") or 0.0
    primary = strategy_tickets(row, VALUE_BUY_PRIMARY_STRATEGY)
    if rate >= 40.0 and primary:
        return {
            "label": "歪み強本命",
            "strategy_id": VALUE_BUY_PRIMARY_STRATEGY,
            "strategy_name": strategy_name(VALUE_BUY_PRIMARY_STRATEGY),
            "reason": "1号艇が世間人気ありなのに、データでは危険。さらに展示タイム・1周タイムの両方が上位3に入らないため、1号艇頭を外して狙う",
            "tickets": primary,
        }
    filtered = strategy_tickets(row, VALUE_BUY_FILTERED_STRATEGY)
    if rate >= 40.0 and filtered:
        return {
            "label": "歪み本命",
            "strategy_id": VALUE_BUY_FILTERED_STRATEGY,
            "strategy_name": strategy_name(VALUE_BUY_FILTERED_STRATEGY),
            "reason": "1号艇が世間人気ありなのにデータでは危険。さらに前半1〜6Rで、1号艇の展示か1周のどちらかが4位以下、展示+1周平均との差もマイナスなので、1号艇頭を外して狙う",
            "tickets": filtered,
        }
    secondary = strategy_tickets(row, VALUE_BUY_SECONDARY_STRATEGY)
    if rate >= 40.0 and secondary:
        return {
            "label": "歪み準本命",
            "strategy_id": VALUE_BUY_SECONDARY_STRATEGY,
            "strategy_name": strategy_name(VALUE_BUY_SECONDARY_STRATEGY),
            "reason": "1号艇は世間人気ありで危険。ただし展示の弱さが本命条件まではそろわないため、買うなら慎重に扱う",
            "tickets": secondary,
        }
    fallback = strategy_tickets(row, VALUE_BUY_FALLBACK_STRATEGY)
    if rate >= 38.0 and fallback:
        return {
            "label": "5/6材料あり補助",
            "strategy_id": VALUE_BUY_FALLBACK_STRATEGY,
            "strategy_name": strategy_name(VALUE_BUY_FALLBACK_STRATEGY),
            "reason": "オッズ込み本命条件は不足。ただし推奨頭に5/6があり、5/6絡みだけなら補助候補",
            "tickets": fallback,
        }
    if rate >= 38.0 and not popular_b1_publicly_backed(row):
        if popular_b1_underbet_value(row):
            reason = "1号艇は世間人気が薄いが、データでは弱くない。万舟狙いで1号艇を無理に飛ばす条件ではないため"
        else:
            reason = "1号艇が世間人気不足。1号艇飛び狙いで入る条件ではないため"
    elif rate >= 38.0:
        reason = "1号艇人気か荒れ材料のどちらかが不足。無理に高配当狙いにしないため"
    else:
        reason = "展示後の万舟率が38%未満のため"
    return {
        "label": "見送り寄り",
        "strategy_id": "",
        "strategy_name": "",
        "reason": reason,
        "tickets": [],
    }


def actual_head(row: dict[str, Any]) -> int | None:
    key = combo_key(row.get("result_trifecta"))
    return parse_int(key[0]) if key else None


def result_boats(row: dict[str, Any]) -> list[int]:
    key = combo_key(row.get("result_trifecta"))
    if not key:
        return []
    return [parse_int(ch) for ch in key if parse_int(ch)]


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).lower() in {"1", "true", "yes", "ok"}


def boat_map(row: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for boat in metrics_boats(row):
        n = boat_number(boat)
        if n:
            out[n] = boat
    return out


def boat_metric(row: dict[str, Any], boat_no: int, key: str) -> float | None:
    boats = boat_map(row)
    if boat_no in boats:
        value = parse_float(boats[boat_no].get(key))
        if value is not None:
            return value
    metrics = read_json_field(row, "metrics_json", {})
    if isinstance(metrics, dict):
        return parse_float(metrics.get(f"boat{boat_no}_{key}") or metrics.get(f"b{boat_no}_{key}"))
    return None


def exhibit_power_score(boat: dict[str, Any]) -> float | None:
    n = boat_number(boat)
    if not n:
        return None
    comp = parse_float(boat.get("composite_win_pct")) or 0.0
    score = comp * 0.65
    for key, weight in [
        ("tenji_rank", 2.8),
        ("isshu_rank", 2.4),
        ("chokusen_rank", 1.4),
        ("mawariashi_rank", 1.4),
        ("start_tenji_rank", 1.2),
    ]:
        rank = parse_float(boat.get(key))
        if rank is not None and 1 <= rank <= 6:
            score += (7 - rank) * weight
    if boolish(boat.get("double_time")):
        score += 5.0
    if boolish(boat.get("super_slit_alert")):
        score += 4.0
    if "バフ" in str(boat.get("matchup_label") or ""):
        score += 3.0
    return score


def slit_matchup_score(boat: dict[str, Any]) -> float | None:
    n = boat_number(boat)
    if not n:
        return None
    score = parse_float(boat.get("composite_win_pct")) or 0.0
    if n >= 3:
        score += 3.0
    if n in {5, 6}:
        score += 1.5
    if boolish(boat.get("super_slit_alert")):
        score += 6.0
    if boolish(boat.get("longshot_head_candidate")):
        score += 4.0
    if boolish(boat.get("low_outer_revive")):
        score += 3.0
    if "バフ" in str(boat.get("matchup_label") or ""):
        score += 4.0
    return score


def honmei_hybrid_score(row: dict[str, Any], boat: dict[str, Any]) -> float | None:
    n = boat_number(boat)
    if not n:
        return None
    rate = row.get("manshu_rate_pct") or 0.0
    comp = parse_float(boat.get("composite_win_pct")) or 0.0
    top3 = parse_float(boat.get("composite_top3_pct")) or 0.0
    score = comp * 0.9 + top3 * 0.12
    if n >= 3:
        score += 5.0
    if n in {5, 6}:
        score += 2.0
    if boolish(boat.get("super_slit_alert")):
        score += 6.0
    if boolish(boat.get("double_time")):
        score += 4.0
    if boolish(boat.get("longshot_head_candidate")):
        score += 4.0
    if "バフ" in str(boat.get("matchup_label") or ""):
        score += 4.0
    for key, bonus in [("tenji_rank", 3.0), ("isshu_rank", 3.0), ("start_tenji_rank", 2.0)]:
        rank = parse_float(boat.get(key))
        if rank is not None and rank <= 2:
            score += bonus
    if n == 1:
        # 本命/強本命は荒れ判定済みなので、1号艇は基本やや割引。
        # ただし複合1着率や展示が抜けている時だけ戻す。
        score -= 5.0 if rate >= 40.0 else 3.0
        if comp >= 34.0:
            score += 5.0
        tenji_rank = parse_float(boat.get("tenji_rank"))
        isshu_rank = parse_float(boat.get("isshu_rank"))
        if tenji_rank is not None and tenji_rank <= 2:
            score += 4.0
        if isshu_rank is not None and isshu_rank <= 2:
            score += 4.0
    return score


def head_candidates(row: dict[str, Any], selector_id: str, count: int = 2) -> list[int]:
    if selector_id == "saved_heads":
        return fallback_heads(row, count=count)
    if selector_id == "composite_win_top2":
        return sorted_boats_by(row, lambda b: parse_float(b.get("composite_win_pct")))[:count]
    if selector_id == "outer_composite_win_top2":
        return sorted_boats_by(row, lambda b: parse_float(b.get("composite_win_pct")), allowed={3, 4, 5, 6})[:count]
    if selector_id == "ai_plus_top2":
        return sorted_boats_by(row, ai_plus_score)[:count]
    if selector_id == "exhibition_power_top2":
        return sorted_boats_by(row, exhibit_power_score)[:count]
    if selector_id == "slit_matchup_top2":
        return sorted_boats_by(row, slit_matchup_score)[:count]
    if selector_id == "honmei_hybrid_v1":
        scored: list[tuple[float, int]] = []
        for boat in metrics_boats(row):
            n = boat_number(boat)
            score = honmei_hybrid_score(row, boat)
            if n and score is not None:
                scored.append((score, n))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [n for _score, n in scored[:count]]
    return []


HEAD_SELECTORS = [
    {
        "id": "saved_heads",
        "name": "現行の頭2艇",
        "logic": "JSONに保存されている頭候補2艇をそのまま使う",
    },
    {
        "id": "composite_win_top2",
        "name": "複合1着率 上位2艇",
        "logic": "AI・一般成績・展示・スリット・相性を混ぜた複合1着率の上位2艇",
    },
    {
        "id": "outer_composite_win_top2",
        "name": "3〜6号艇 複合1着率上位2艇",
        "logic": "万舟は外頭が多い前提で、3〜6号艇だけから複合1着率上位2艇",
    },
    {
        "id": "ai_plus_top2",
        "name": "AI+一般3連対 上位2艇",
        "logic": "AI3連対率と一般3連対率の合計が高い2艇",
    },
    {
        "id": "exhibition_power_top2",
        "name": "展示パワー 上位2艇",
        "logic": "複合1着率に展示タイム・1周・直線・回り足・展示ST・ダブルタイムを加点",
    },
    {
        "id": "slit_matchup_top2",
        "name": "スリット+相性 上位2艇",
        "logic": "複合1着率にスーパースリット、対戦相性、穴頭候補を強めに加点",
    },
    {
        "id": "honmei_hybrid_v1",
        "name": "本命専用ハイブリッドV1",
        "logic": "3〜6号艇を優先しつつ、1号艇が複合1着率・展示で抜けた時だけ戻す",
    },
]


def eval_head_selector(records: list[dict[str, Any]], selector_id: str, segment: str, pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    settled = [r for r in records if pred(r) and actual_head(r) is not None]
    top1_hits = 0
    top2_hits = 0
    empty = 0
    winner_counts: dict[str, int] = defaultdict(int)
    selected_counts: dict[str, int] = defaultdict(int)
    examples_hit = []
    examples_miss = []
    for row in settled:
        winner = actual_head(row)
        if winner is None:
            continue
        winner_counts[str(winner)] += 1
        candidates = head_candidates(row, selector_id, 2)
        if not candidates:
            empty += 1
            continue
        for c in candidates:
            selected_counts[str(c)] += 1
        hit1 = candidates[0] == winner
        hit2 = winner in candidates[:2]
        top1_hits += int(hit1)
        top2_hits += int(hit2)
        example = {
            "date": row.get("date"),
            "race": f"{row.get('place_name')}{row.get('round')}R",
            "rate": row.get("manshu_rate_pct"),
            "winner": winner,
            "candidates": candidates[:2],
            "result": row.get("result_trifecta"),
            "payout_yen": row.get("payout_yen"),
        }
        if hit2 and len(examples_hit) < 4:
            examples_hit.append(example)
        if not hit2 and len(examples_miss) < 4:
            examples_miss.append(example)
    n = len(settled)
    top1_rate = round(top1_hits / n * 100, 2) if n else None
    top2_rate = round(top2_hits / n * 100, 2) if n else None
    if n < 30:
        verdict = "保留（件数不足）"
    elif top2_rate is not None and top2_rate >= 58:
        verdict = "採用候補"
    elif top2_rate is not None and top2_rate >= 45:
        verdict = "保留"
    else:
        verdict = "却下"
    return {
        "selector_id": selector_id,
        "segment": segment,
        "races": n,
        "empty_predictions": empty,
        "top1_hits": top1_hits,
        "top1_hit_rate_pct": top1_rate,
        "top2_hits": top2_hits,
        "top2_capture_rate_pct": top2_rate,
        "winner_counts": dict(sorted(winner_counts.items(), key=lambda x: int(x[0]))),
        "selected_counts": dict(sorted(selected_counts.items(), key=lambda x: int(x[0]))),
        "examples_hit": examples_hit,
        "examples_miss": examples_miss,
        "verdict": verdict,
    }


def build_head_research(records: list[dict[str, Any]]) -> dict[str, Any]:
    segments: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("本命40%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("本命/準本命38%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0),
        ("一般戦 本命40%以上", lambda r: is_general_race(r) and (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("一般戦 本命40%以上 展示6艇", lambda r: is_general_race(r) and (r.get("manshu_rate_pct") or 0) >= 40.0 and has_full_exhibition(r)),
        ("朝監視TOP10", lambda r: (r.get("rank") or 999) <= 10),
    ]
    rows = []
    for segment_name, pred in segments:
        for selector in HEAD_SELECTORS:
            item = eval_head_selector(records, selector["id"], segment_name, pred)
            item["selector_name"] = selector["name"]
            item["logic"] = selector["logic"]
            rows.append(item)
    rows.sort(key=lambda x: (x["segment"], -(x.get("top2_capture_rate_pct") or -1), -(x.get("top1_hit_rate_pct") or -1)))
    by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_segment[row["segment"]].append(row)
    best = []
    for segment_name, items in by_segment.items():
        candidates = [x for x in items if (x.get("races") or 0) >= 10]
        if candidates:
            best.append(max(candidates, key=lambda x: ((x.get("top2_capture_rate_pct") or -1), x.get("top1_hit_rate_pct") or -1)))
    best.sort(key=lambda x: (-(x.get("top2_capture_rate_pct") or -1), -(x.get("top1_hit_rate_pct") or -1)))
    return {
        "selectors": HEAD_SELECTORS,
        "rows": rows,
        "best_by_segment": best,
        "note": "頭精度は1着艇が1番手にいる率と、2艇候補内に入る率で評価します。結果があるレースだけが対象です。",
    }


def recommended_head_selector(row: dict[str, Any]) -> str:
    rate = row.get("manshu_rate_pct") or 0.0
    if rate >= 40.0:
        return "composite_win_top2"
    if rate >= 38.0:
        return "honmei_hybrid_v1"
    return "saved_heads"


def head_selector_name(selector_id: str) -> str:
    for selector in HEAD_SELECTORS:
        if selector["id"] == selector_id:
            return selector["name"]
    return selector_id


def strategy_name(strategy_id: str) -> str:
    for strategy in BUY_STRATEGIES:
        if strategy["id"] == strategy_id:
            return strategy["name"]
    return strategy_id


def strategy_logic(strategy_id: str) -> str:
    for strategy in BUY_STRATEGIES:
        if strategy["id"] == strategy_id:
            return strategy["logic"]
    return ""


def metrics_map(row: dict[str, Any]) -> dict[str, Any]:
    metrics = read_json_field(row, "metrics_json", {})
    return metrics if isinstance(metrics, dict) else {}


def popular_b1_danger(row: dict[str, Any]) -> bool:
    metrics = metrics_map(row)
    level = str(metrics.get("popular_b1_fly_level") or "")
    score = parse_float(metrics.get("popular_b1_fly_score")) or 0.0
    return level in {"危険", "超危険"} or score >= 70.0


def popular_b1_publicly_backed(row: dict[str, Any]) -> bool:
    metrics = metrics_map(row)
    if boolish(metrics.get("popular_b1_is_popular")):
        return True
    if (parse_float(metrics.get("trifecta_top5_head1_count")) or 0.0) >= 3.0:
        return True
    b1_odds_rank = parse_float(metrics.get("boat1_odds_rank"))
    b1_odds_pct = parse_float(metrics.get("boat1_odds_prediction_pct")) or 0.0
    return b1_odds_rank == 1.0 and b1_odds_pct >= 40.0


def popular_b1_top5_dominant(row: dict[str, Any]) -> bool:
    metrics = metrics_map(row)
    return boolish(metrics.get("b1_trifecta_top5_1head")) or (parse_float(metrics.get("trifecta_top5_head1_count")) or 0.0) >= 5.0


def popular_b1_overbet_danger(row: dict[str, Any]) -> bool:
    return popular_b1_publicly_backed(row) and popular_b1_danger(row)


def boat_metrics(row: dict[str, Any], number: int) -> dict[str, Any]:
    for boat in metrics_boats(row):
        if boat_number(boat) == number:
            return boat
    return {}


def valid_boat_rank(value: Any) -> float | None:
    rank = parse_float(value)
    if rank is None or rank < 1.0 or rank > 6.0:
        return None
    return rank


def popular_b1_exhibition_double_debuff(row: dict[str, Any]) -> bool:
    """1号艇が展示タイム・1周タイムの両方で上位3に入らない状態."""

    boat = boat_metrics(row, 1)
    tenji_rank = valid_boat_rank(boat.get("tenji_rank"))
    isshu_rank = valid_boat_rank(boat.get("isshu_rank"))
    return tenji_rank is not None and isshu_rank is not None and tenji_rank > 3.0 and isshu_rank > 3.0


def popular_b1_exhibition_weak(row: dict[str, Any]) -> bool:
    boat = boat_metrics(row, 1)
    tenji_rank = valid_boat_rank(boat.get("tenji_rank"))
    isshu_rank = valid_boat_rank(boat.get("isshu_rank"))
    avg_diff = parse_float(boat.get("avg_isshu_diff"))
    rank_weak = (tenji_rank is not None and tenji_rank > 3.0) or (isshu_rank is not None and isshu_rank > 3.0)
    avg_weak = avg_diff is not None and avg_diff < 0.10
    return popular_b1_exhibition_double_debuff(row) or (rank_weak and avg_weak)


def popular_b1_overbet_strong(row: dict[str, Any]) -> bool:
    return popular_b1_overbet_danger(row) and popular_b1_exhibition_double_debuff(row)


def popular_b1_overbet_filtered(row: dict[str, Any]) -> bool:
    if not popular_b1_overbet_danger(row):
        return False
    try:
        if int(row.get("round") or 99) > 6:
            return False
    except (TypeError, ValueError):
        return False
    boat = boat_metrics(row, 1)
    tenji_rank = valid_boat_rank(boat.get("tenji_rank"))
    isshu_rank = valid_boat_rank(boat.get("isshu_rank"))
    avg_diff = parse_float(boat.get("avg_isshu_diff"))
    one_rank_weak = (tenji_rank is not None and tenji_rank > 3.0) or (isshu_rank is not None and isshu_rank > 3.0)
    return one_rank_weak and avg_diff is not None and avg_diff < 0.0


def popular_b1_underbet_value(row: dict[str, Any]) -> bool:
    boat = boat_metrics(row, 1)
    composite_win = parse_float(boat.get("composite_win_pct")) or 0.0
    composite_top3 = parse_float(boat.get("composite_top3_pct")) or 0.0
    return (not popular_b1_publicly_backed(row)) and (not popular_b1_danger(row)) and (composite_win >= 55.0 or composite_top3 >= 70.0)


def popular_b1_odds_gap_label(row: dict[str, Any]) -> str:
    if popular_b1_overbet_strong(row):
        return "1号艇売れすぎ強危険"
    if popular_b1_overbet_filtered(row):
        return "1号艇売れすぎ危険"
    if popular_b1_overbet_danger(row):
        return "1号艇人気だが危険"
    if popular_b1_underbet_value(row):
        return "1号艇人気薄だがデータ強"
    if popular_b1_publicly_backed(row):
        return "1号艇人気どおり"
    if popular_b1_danger(row):
        return "世間も1号艇を疑い"
    return "大きな歪みなし"


def popular_b1_odds_gap_reasons(row: dict[str, Any]) -> list[str]:
    metrics = metrics_map(row)
    boat = boat_metrics(row, 1)
    reasons: list[str] = []
    source = str(metrics.get("popular_b1_source") or "")
    if source:
        reasons.append(source)
    if popular_b1_top5_dominant(row):
        reasons.append("三連単人気上位が1号艇頭に寄っている")
    elif popular_b1_publicly_backed(row):
        reasons.append("1号艇が世間またはAIオッズ評価で買われている")
    level = str(metrics.get("popular_b1_fly_level") or "")
    score = parse_float(metrics.get("popular_b1_fly_score"))
    if popular_b1_danger(row) and (level or score is not None):
        reasons.append(f"1号艇危険度 {level or '判定あり'} {score:.0f}点" if score is not None else f"1号艇危険度 {level}")
    tenji_rank = valid_boat_rank(boat.get("tenji_rank"))
    isshu_rank = valid_boat_rank(boat.get("isshu_rank"))
    avg_diff = parse_float(boat.get("avg_isshu_diff"))
    show_exhibition_reason = popular_b1_publicly_backed(row) or popular_b1_danger(row) or popular_b1_underbet_value(row)
    if show_exhibition_reason and popular_b1_exhibition_double_debuff(row):
        reasons.append(f"1号艇の展示タイム{tenji_rank:.0f}位・1周{isshu_rank:.0f}位でどちらも上位3外")
    elif show_exhibition_reason and popular_b1_exhibition_weak(row):
        chunks = []
        if tenji_rank is not None:
            chunks.append(f"展示{tenji_rank:.0f}位")
        if isshu_rank is not None:
            chunks.append(f"1周{isshu_rank:.0f}位")
        if avg_diff is not None:
            chunks.append(f"平均との差{avg_diff:+.2f}")
        reasons.append("1号艇の展示が弱め（" + "・".join(chunks) + "）")
    if popular_b1_underbet_value(row):
        reasons.append("世間人気は薄いが、複合1着率または3着内率は高め")
    return reasons[:4]


def outer56_support_signal(row: dict[str, Any]) -> bool:
    metrics = metrics_map(row)
    if (parse_float(metrics.get("outer56_super_slit_count")) or 0.0) >= 1.0:
        return True
    if (parse_float(metrics.get("outer56_double_time_count")) or 0.0) >= 1.0:
        return True
    best_diff = parse_float(metrics.get("outer56_best_avg_isshu_diff"))
    best_ai = parse_float(metrics.get("outer56_best_ai_prediction_pct"))
    if best_diff is not None and best_ai is not None and best_diff >= 0.25 and best_ai >= 8.0:
        return True
    for boat in metrics_boats(row):
        n = boat_number(boat)
        if n not in {5, 6}:
            continue
        top3 = parse_float(boat.get("composite_top3_pct")) or 0.0
        if top3 >= 28.0 or boolish(boat.get("super_slit_alert")) or boolish(boat.get("double_time")):
            return True
    return False


HEAD_VALUE_PATTERNS = [
    {
        "id": "all",
        "name": "本命レース全体",
        "usable_before_race": True,
        "logic": "展示後40%以上の本命を全部見る",
        "pred": lambda _row, _heads: True,
    },
    {
        "id": "head_captured",
        "name": "実際に頭2艇で1着を拾えた",
        "usable_before_race": False,
        "logic": "結果確認用。予想した頭2艇に実際の1着艇が入ったレース",
        "pred": lambda row, heads: actual_head(row) in heads,
    },
    {
        "id": "head_missed",
        "name": "実際に頭2艇を外した",
        "usable_before_race": False,
        "logic": "結果確認用。予想した頭2艇に実際の1着艇が入らなかったレース",
        "pred": lambda row, heads: actual_head(row) is not None and actual_head(row) not in heads,
    },
    {
        "id": "heads_include_1",
        "name": "頭候補に1号艇あり",
        "usable_before_race": True,
        "logic": "買う前に分かる形。頭2艇の中に1号艇が入っている",
        "pred": lambda _row, heads: 1 in heads,
    },
    {
        "id": "heads_exclude_1",
        "name": "頭候補に1号艇なし",
        "usable_before_race": True,
        "logic": "買う前に分かる形。頭2艇から1号艇を外している",
        "pred": lambda _row, heads: bool(heads) and 1 not in heads,
    },
    {
        "id": "heads_inner_only",
        "name": "頭候補が1・2号艇だけ",
        "usable_before_race": True,
        "logic": "買う前に分かる形。頭2艇が内寄りだけで、配当が安くなりやすい形",
        "pred": lambda _row, heads: len(heads) >= 2 and set(heads[:2]).issubset({1, 2}),
    },
    {
        "id": "heads_have_outer",
        "name": "頭候補に3〜6号艇あり",
        "usable_before_race": True,
        "logic": "買う前に分かる形。頭2艇のどちらかが3〜6号艇",
        "pred": lambda _row, heads: any(h in {3, 4, 5, 6} for h in heads),
    },
    {
        "id": "heads_have_56",
        "name": "頭候補に5・6号艇あり",
        "usable_before_race": True,
        "logic": "買う前に分かる形。頭2艇のどちらかが5号艇か6号艇",
        "pred": lambda _row, heads: any(h in {5, 6} for h in heads),
    },
    {
        "id": "popular_b1_danger",
        "name": "人気1号艇危険あり",
        "usable_before_race": True,
        "logic": "買う前に分かる形。人気の1号艇に飛び材料がある",
        "pred": lambda row, _heads: popular_b1_danger(row),
    },
    {
        "id": "popular_b1_overbet_danger",
        "name": "1号艇が売れているのに危険",
        "usable_before_race": True,
        "logic": "買う前に分かる形。オッズやAIオッズで1号艇が人気なのに、展示や複合条件で危険",
        "pred": lambda row, _heads: popular_b1_overbet_danger(row),
    },
    {
        "id": "popular_b1_top5_dominant",
        "name": "三連単上位が1号艇頭寄り",
        "usable_before_race": True,
        "logic": "買う前に分かる形。三連単上位5点が1号艇頭に寄っている。現状は保存件数が少ないため参考",
        "pred": lambda row, _heads: popular_b1_top5_dominant(row),
    },
    {
        "id": "outer56_support",
        "name": "5・6号艇絡み予兆あり",
        "usable_before_race": True,
        "logic": "買う前に分かる形。5・6号艇に展示、スリット、AI、複合3着内のどれか良い材料がある",
        "pred": lambda row, _heads: outer56_support_signal(row),
    },
    {
        "id": "danger_outer56",
        "name": "1号艇危険＋5・6予兆",
        "usable_before_race": True,
        "logic": "買う前に分かる形。1号艇が危なく、さらに5・6号艇にも絡む材料がある",
        "pred": lambda row, _heads: popular_b1_danger(row) and outer56_support_signal(row),
    },
]


def eval_head_value_pattern(
    records: list[dict[str, Any]],
    selector_id: str,
    segment: str,
    segment_pred: Callable[[dict[str, Any]], bool],
    pattern: dict[str, Any],
) -> dict[str, Any]:
    settled: list[dict[str, Any]] = []
    for row in records:
        if not segment_pred(row) or row.get("payout_yen") is None or actual_head(row) is None:
            continue
        heads = head_candidates(row, selector_id, 2)
        if heads and pattern["pred"](row, heads):
            settled.append(row)

    head_hits = 0
    manshu = 0
    high_payout = 0
    with_56 = 0
    b1_not_win = 0
    payouts: list[int] = []
    examples = []
    for row in settled:
        heads = head_candidates(row, selector_id, 2)
        result = result_boats(row)
        payout = row.get("payout_yen") or 0
        payouts.append(payout)
        hit = actual_head(row) in heads
        head_hits += int(hit)
        manshu += int(bool(row.get("is_manshu")))
        high_payout += int(payout >= 5000)
        with_56 += int(any(n in {5, 6} for n in result))
        b1_not_win += int(actual_head(row) != 1)
        if (row.get("is_manshu") or payout >= 5000) and len(examples) < 5:
            examples.append(
                {
                    "date": row.get("date"),
                    "race": f"{row.get('place_name')}{row.get('round')}R",
                    "rate": row.get("manshu_rate_pct"),
                    "heads": heads,
                    "result": row.get("result_trifecta"),
                    "payout_yen": payout,
                    "head_hit": hit,
                }
            )

    n = len(settled)
    median_payout = None
    if payouts:
        payouts.sort()
        mid = len(payouts) // 2
        median_payout = payouts[mid] if len(payouts) % 2 else round((payouts[mid - 1] + payouts[mid]) / 2)
    if n < 20:
        verdict = "保留（件数不足）"
    elif (manshu / n * 100) >= 12.0 and (head_hits / n * 100) >= 55.0:
        verdict = "注目"
    elif (head_hits / n * 100) >= 65.0:
        verdict = "頭精度は高い"
    elif (manshu / n * 100) >= 12.0:
        verdict = "荒れやすいが頭注意"
    else:
        verdict = "参考"
    return {
        "selector_id": selector_id,
        "selector_name": head_selector_name(selector_id),
        "segment": segment,
        "pattern_id": pattern["id"],
        "pattern_name": pattern["name"],
        "usable_before_race": bool(pattern["usable_before_race"]),
        "logic": pattern["logic"],
        "races": n,
        "head_hits": head_hits,
        "head_capture_rate_pct": round(head_hits / n * 100, 2) if n else None,
        "manshu_count": manshu,
        "manshu_rate_pct": round(manshu / n * 100, 2) if n else None,
        "high_payout_count": high_payout,
        "high_payout_rate_pct": round(high_payout / n * 100, 2) if n else None,
        "result_has_56_count": with_56,
        "result_has_56_rate_pct": round(with_56 / n * 100, 2) if n else None,
        "b1_not_win_count": b1_not_win,
        "b1_not_win_rate_pct": round(b1_not_win / n * 100, 2) if n else None,
        "median_payout_yen": median_payout,
        "max_payout_yen": max(payouts) if payouts else None,
        "examples": examples,
        "verdict": verdict,
    }


def build_head_value_research(records: list[dict[str, Any]]) -> dict[str, Any]:
    segments: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
        ("本命40%以上 × 複合1着率", "composite_win_top2", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("本命40%以上 × AI+上位", "ai_plus_top2", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("展示後38%以上 × ハイブリッド", "honmei_hybrid_v1", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0),
    ]
    rows = []
    for segment_name, selector_id, pred in segments:
        for pattern in HEAD_VALUE_PATTERNS:
            rows.append(eval_head_value_pattern(records, selector_id, segment_name, pred, pattern))
    rows.sort(
        key=lambda x: (
            x["segment"],
            not x.get("usable_before_race"),
            -(x.get("races") or 0),
            -(x.get("manshu_rate_pct") or -1),
            -(x.get("head_capture_rate_pct") or -1),
        )
    )
    actionable = [r for r in rows if r.get("usable_before_race") and (r.get("races") or 0) >= 10]
    actionable.sort(key=lambda x: (-(x.get("manshu_rate_pct") or -1), -(x.get("head_capture_rate_pct") or -1), -(x.get("races") or 0)))
    outcome = [r for r in rows if not r.get("usable_before_race")]
    return {
        "rows": rows,
        "best_actionable": actionable[:8],
        "outcome_checks": outcome,
        "note": "頭を当てる力と、配当が跳ねる力は別物です。買う前に使える条件と、結果確認だけの条件を分けて表示します。",
    }


def write_head_value_research_db(db_path: Path, rows: list[dict[str, Any]]) -> None:
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS head_value_summary")
    con.execute(
        """
        CREATE TABLE head_value_summary (
          selector_id TEXT,
          selector_name TEXT,
          segment TEXT,
          pattern_id TEXT,
          pattern_name TEXT,
          usable_before_race INTEGER,
          logic TEXT,
          races INTEGER,
          head_hits INTEGER,
          head_capture_rate_pct REAL,
          manshu_count INTEGER,
          manshu_rate_pct REAL,
          high_payout_count INTEGER,
          high_payout_rate_pct REAL,
          result_has_56_count INTEGER,
          result_has_56_rate_pct REAL,
          b1_not_win_count INTEGER,
          b1_not_win_rate_pct REAL,
          median_payout_yen INTEGER,
          max_payout_yen INTEGER,
          verdict TEXT,
          examples_json TEXT
        )
        """
    )
    cols = [
        "selector_id",
        "selector_name",
        "segment",
        "pattern_id",
        "pattern_name",
        "usable_before_race",
        "logic",
        "races",
        "head_hits",
        "head_capture_rate_pct",
        "manshu_count",
        "manshu_rate_pct",
        "high_payout_count",
        "high_payout_rate_pct",
        "result_has_56_count",
        "result_has_56_rate_pct",
        "b1_not_win_count",
        "b1_not_win_rate_pct",
        "median_payout_yen",
        "max_payout_yen",
        "verdict",
        "examples_json",
    ]
    values = []
    for row in rows:
        values.append([int(row.get(col)) if col == "usable_before_race" else (compact_json(row.get("examples") or []) if col == "examples_json" else row.get(col)) for col in cols])
    con.executemany(
        f"INSERT INTO head_value_summary ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        values,
    )
    con.commit()
    con.close()


def write_head_research_db(db_path: Path, rows: list[dict[str, Any]]) -> None:
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS head_selector_summary")
    con.execute(
        """
        CREATE TABLE head_selector_summary (
          selector_id TEXT,
          selector_name TEXT,
          segment TEXT,
          races INTEGER,
          top1_hits INTEGER,
          top1_hit_rate_pct REAL,
          top2_hits INTEGER,
          top2_capture_rate_pct REAL,
          empty_predictions INTEGER,
          verdict TEXT,
          logic TEXT,
          winner_counts_json TEXT,
          selected_counts_json TEXT,
          examples_hit_json TEXT,
          examples_miss_json TEXT
        )
        """
    )
    cols = [
        "selector_id",
        "selector_name",
        "segment",
        "races",
        "top1_hits",
        "top1_hit_rate_pct",
        "top2_hits",
        "top2_capture_rate_pct",
        "empty_predictions",
        "verdict",
        "logic",
        "winner_counts_json",
        "selected_counts_json",
        "examples_hit_json",
        "examples_miss_json",
    ]
    values = []
    for row in rows:
        values.append(
            [
                row.get("selector_id"),
                row.get("selector_name"),
                row.get("segment"),
                row.get("races"),
                row.get("top1_hits"),
                row.get("top1_hit_rate_pct"),
                row.get("top2_hits"),
                row.get("top2_capture_rate_pct"),
                row.get("empty_predictions"),
                row.get("verdict"),
                row.get("logic"),
                compact_json(row.get("winner_counts") or {}),
                compact_json(row.get("selected_counts") or {}),
                compact_json(row.get("examples_hit") or []),
                compact_json(row.get("examples_miss") or []),
            ]
        )
    con.executemany(
        f"INSERT INTO head_selector_summary ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        values,
    )
    con.commit()
    con.close()


BUY_STRATEGIES = [
    {
        "id": "saved_current",
        "name": "現行保存買い目",
        "logic": "JSONに保存されているその時点の買い目をそのまま買う",
    },
    {
        "id": "head2_axis2_current_15",
        "name": "頭2×軸2 15点",
        "logic": "頭候補2艇と軸候補2艇。消し以外へ2・3着折り返しで最大15点",
    },
    {
        "id": "head1_axis2_current",
        "name": "頭1×軸2",
        "logic": "頭候補を1艇に絞り、軸候補2艇を2・3着に置く",
    },
    {
        "id": "head2_axis1_current",
        "name": "頭2×軸1",
        "logic": "頭候補2艇、軸候補1艇。点数を抑える形",
    },
    {
        "id": "outer_head2_ai23_12",
        "name": "外頭2×AI+3連対2・3位軸 12点",
        "logic": "3〜6号艇から複合1着上位2艇を頭、AI+一般3連対の2・3位を軸",
    },
    {
        "id": "outer_head2_ai3_8",
        "name": "外頭2×AI+3連対3位軸 8点",
        "logic": "3〜6号艇から頭2艇、AI+一般3連対3位だけを軸にする省点数型",
    },
    {
        "id": "outer_head2_no1_ai23_12",
        "name": "1号艇抜き外頭2×AI+2・3位軸",
        "logic": "1号艇を2・3着からも外し、外頭2艇とAI+一般3連対2・3位軸で買う",
    },
    {
        "id": "odds_gap_b1_fade_strong_12",
        "name": "歪み強本命 1号艇売れすぎ強危険12点",
        "logic": "1号艇が世間で売れているのに、データでは危険。さらに1号艇の展示タイムと1周タイムが両方4位以下の時だけ、1号艇頭を外して2〜6号艇の複合1着率上位2艇から買う",
    },
    {
        "id": "odds_gap_b1_fade_filtered_12",
        "name": "歪み本命 1号艇売れすぎ危険 絞り込み12点",
        "logic": "1号艇が世間で売れているのにデータでは危険。さらに1〜6Rで、1号艇の展示タイムまたは1周タイムが4位以下、展示+1周平均との差がマイナスの時だけ1号艇頭を外す",
    },
    {
        "id": "odds_b1_fade_comp_ai13_12",
        "name": "オッズ重視 1号艇人気危険なら頭外し12点",
        "logic": "1号艇が世間人気あり、かつ危険な時だけ買う。頭は2〜6号艇の複合1着率上位2艇、軸はAI+一般3連対の1位・3位。5/6は必須にしない",
    },
    {
        "id": "value_ai_head2_ai23_has56_12",
        "name": "高配当向け AI頭2×AI+2・3位軸 5/6絡み",
        "logic": "展示後38%以上で推奨頭に5/6が入る時だけ、AI+上位2艇を頭、AI+2・3位を軸にし、5/6が絡まない安い買い目を削る最大12点",
    },
    {
        "id": "value_ai_head2_ai23_no1head56_12",
        "name": "高配当向け 1号艇頭なし 5/6絡み",
        "logic": "推奨頭に5/6が入る時だけ、AI+上位2艇頭の買い目から1号艇頭と5/6なしを削る強気型",
    },
    {
        "id": "value_hybrid_head2_ai23_has56_12",
        "name": "高配当向け ハイブリッド頭2 5/6絡み",
        "logic": "推奨頭に5/6が入る時だけ、本命専用ハイブリッド頭2艇とAI+2・3位軸で、5/6絡みだけ買う",
    },
    {
        "id": "value_comp_ai13_outer_or_56_12",
        "name": "高配当向け 複合頭2×AI+1・3位軸",
        "logic": "複合1着率上位2艇を頭、AI+1・3位を軸にし、外頭または5/6絡みだけを残す",
    },
    {
        "id": "three_boat_box",
        "name": "3艇BOX",
        "logic": "頭候補と軸候補から3艇に絞り、3連単BOX6点",
    },
    {
        "id": "outer3_boat_box",
        "name": "外3艇BOX",
        "logic": "3〜6号艇の中から複合1着・3着内が強い3艇でBOX6点",
    },
]


def is_general_race(row: dict[str, Any]) -> bool:
    grade = str(row.get("race_grade") or "")
    kind = str(row.get("race_kind") or "")
    series = str(row.get("series_title") or "")
    return grade == "Ippan" or "一般" in kind or "一般" in series


def has_full_exhibition(row: dict[str, Any]) -> bool:
    return (row.get("tenji_boats") or 0) >= 6 and ((row.get("isshu_boats") or 0) >= 6 or (row.get("raw_isshu_boats") or 0) >= 6)


def strategy_eval(records: list[dict[str, Any]], strategy_id: str, segment: str, pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    settled = [r for r in records if pred(r) and r.get("payout_yen") is not None]
    bought = []
    for row in settled:
        tickets = strategy_tickets(row, strategy_id)
        if tickets:
            bought.append((row, tickets))
    stake = sum(len(tickets) * 100 for _row, tickets in bought)
    hits = 0
    manshu_hits = 0
    payback = 0
    max_losing = 0
    current_losing = 0
    biggest_hit = 0
    total_points = 0
    examples = []
    for row, tickets in bought:
        total_points += len(tickets)
        result_key = combo_key(row.get("result_trifecta"))
        hit = bool(result_key and result_key in {combo_key(t) for t in tickets})
        if hit:
            hits += 1
            current_losing = 0
            payout = row.get("payout_yen") or 0
            payback += payout
            biggest_hit = max(biggest_hit, payout)
            if row.get("is_manshu"):
                manshu_hits += 1
            if len(examples) < 6:
                examples.append(
                    {
                        "date": row.get("date"),
                        "race": f"{row.get('place_name')}{row.get('round')}R",
                        "result": row.get("result_trifecta"),
                        "payout_yen": payout,
                        "tickets": tickets[:15],
                    }
                )
        else:
            current_losing += 1
            max_losing = max(max_losing, current_losing)
    roi = round(payback / stake * 100, 2) if stake else None
    buy_races = len(bought)
    dependency_pct = round(biggest_hit / payback * 100, 2) if payback else None
    high_payout_dependent = bool(dependency_pct is not None and dependency_pct >= 65.0)
    if buy_races < 50:
        verdict = "保留（件数不足）"
    elif high_payout_dependent and roi is not None and roi >= 100:
        verdict = "保留（高配当依存）"
    elif roi is not None and roi >= 100:
        verdict = "採用候補"
    elif roi is not None and roi >= 80:
        verdict = "保留"
    else:
        verdict = "却下"
    return {
        "strategy_id": strategy_id,
        "segment": segment,
        "target_races": len(settled),
        "buy_races": buy_races,
        "total_points": total_points,
        "avg_points": round(total_points / buy_races, 2) if buy_races else None,
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": roi,
        "hits": hits,
        "hit_rate_pct": round(hits / buy_races * 100, 2) if buy_races else None,
        "manshu_hits": manshu_hits,
        "manshu_hit_rate_pct": round(manshu_hits / buy_races * 100, 2) if buy_races else None,
        "max_losing_streak": max_losing,
        "max_hit_payout_yen": biggest_hit or None,
        "payback_dependency_pct": dependency_pct,
        "verdict": verdict,
        "examples": examples,
    }


def build_strategy_research(records: list[dict[str, Any]]) -> dict[str, Any]:
    segments: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("朝監視TOP10", lambda r: (r.get("rank") or 999) <= 10),
        ("展示後38%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0),
        ("展示後38%以上＋推奨頭5/6あり", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0 and any(h in {5, 6} for h in head_candidates(r, "honmei_hybrid_v1", 2))),
        ("展示後38%以上＋5/6予兆", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0 and outer56_support_signal(r)),
        ("準本命38-39.9", lambda r: 38.0 <= (r.get("manshu_rate_pct") or 0) < 40.0),
        ("本命40%以上", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("本命40%以上＋人気1号艇危険", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and popular_b1_danger(r)),
        ("本命40%以上＋1号艇人気あり危険", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and popular_b1_overbet_danger(r)),
        ("本命40%以上＋1号艇歪み本命", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and popular_b1_overbet_filtered(r)),
        ("本命40%以上＋1号艇歪み強本命", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and popular_b1_overbet_strong(r)),
        ("展示後38%以上＋1号艇歪み本命", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0 and popular_b1_overbet_filtered(r)),
        ("展示後38%以上＋1号艇歪み強本命", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0 and popular_b1_overbet_strong(r)),
        ("展示後38%以上＋1号艇人気薄データ強", lambda r: (r.get("manshu_rate_pct") or 0) >= 38.0 and popular_b1_underbet_value(r)),
        ("本命40%以上＋三連単上位1号艇頭", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and popular_b1_top5_dominant(r) and popular_b1_danger(r)),
        ("本命40%以上＋5/6予兆", lambda r: (r.get("manshu_rate_pct") or 0) >= 40.0 and outer56_support_signal(r)),
        ("一般戦 本命40%以上", lambda r: is_general_race(r) and (r.get("manshu_rate_pct") or 0) >= 40.0),
        ("一般戦 本命40%以上 展示6艇", lambda r: is_general_race(r) and (r.get("manshu_rate_pct") or 0) >= 40.0 and has_full_exhibition(r)),
        ("買い目あり", lambda r: (r.get("ticket_count") or 0) > 0),
    ]
    rows = []
    for segment_name, pred in segments:
        for strategy in BUY_STRATEGIES:
            item = strategy_eval(records, strategy["id"], segment_name, pred)
            item["strategy_name"] = strategy["name"]
            item["logic"] = strategy["logic"]
            rows.append(item)
    rows.sort(key=lambda x: (x["segment"], -(x["roi_pct"] or -1), -(x["buy_races"] or 0)))
    by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_segment[row["segment"]].append(row)
    best = []
    for segment_name, items in by_segment.items():
        candidates = [x for x in items if (x.get("buy_races") or 0) >= 10]
        if not candidates:
            candidates = items
        if candidates:
            best.append(max(candidates, key=lambda x: ((x.get("roi_pct") or -1), x.get("buy_races") or 0)))
    best.sort(key=lambda x: (-(x.get("roi_pct") or -1), -(x.get("buy_races") or 0)))
    return {
        "strategies": BUY_STRATEGIES,
        "rows": rows,
        "best_by_segment": best,
        "note": "1点100円均等買い。結果があるレースだけを計算し、返還等の特殊処理は保存JSONに依存します。件数30未満は採用ではなく保留扱いです。",
    }


def write_strategy_research_db(db_path: Path, rows: list[dict[str, Any]]) -> None:
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS buy_strategy_summary")
    con.execute(
        """
        CREATE TABLE buy_strategy_summary (
          strategy_id TEXT,
          strategy_name TEXT,
          segment TEXT,
          target_races INTEGER,
          buy_races INTEGER,
          total_points INTEGER,
          avg_points REAL,
          stake_yen INTEGER,
          payback_yen INTEGER,
          profit_yen INTEGER,
          roi_pct REAL,
          hits INTEGER,
          hit_rate_pct REAL,
          manshu_hits INTEGER,
          manshu_hit_rate_pct REAL,
          max_losing_streak INTEGER,
          max_hit_payout_yen INTEGER,
          payback_dependency_pct REAL,
          verdict TEXT,
          logic TEXT,
          examples_json TEXT
        )
        """
    )
    cols = [
        "strategy_id",
        "strategy_name",
        "segment",
        "target_races",
        "buy_races",
        "total_points",
        "avg_points",
        "stake_yen",
        "payback_yen",
        "profit_yen",
        "roi_pct",
        "hits",
        "hit_rate_pct",
        "manshu_hits",
        "manshu_hit_rate_pct",
        "max_losing_streak",
        "max_hit_payout_yen",
        "payback_dependency_pct",
        "verdict",
        "logic",
        "examples_json",
    ]
    values = []
    for row in rows:
        values.append([row.get(col) if col != "examples_json" else compact_json(row.get("examples") or []) for col in cols])
    con.executemany(
        f"INSERT INTO buy_strategy_summary ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        values,
    )
    con.commit()
    con.close()


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
                "recommended_heads": ",".join(map(str, head_candidates(r, recommended_head_selector(r), 2))),
                "recommended_head_logic": head_selector_name(recommended_head_selector(r)),
                "axes": r.get("axis_boats"),
                "keshi": r.get("keshi_boat"),
                "ticket_count": r.get("ticket_count"),
                "ticket_hit": bool(r.get("ticket_hit")),
                "odds_gap": {
                    "label": popular_b1_odds_gap_label(r),
                    "reasons": popular_b1_odds_gap_reasons(r),
                },
                "value_buy": {
                    "label": value_buy_recommendation(r)["label"],
                    "strategy_name": value_buy_recommendation(r)["strategy_name"],
                    "reason": value_buy_recommendation(r)["reason"],
                    "points": len(value_buy_recommendation(r)["tickets"]),
                    "tickets": value_buy_recommendation(r)["tickets"][:12],
                },
                "result_trifecta": r.get("result_trifecta"),
                "payout_yen": r.get("payout_yen"),
                "is_manshu": bool(r.get("is_manshu")),
            }
            for r in view_rows
        ],
    }


def build_summary(rows: list[dict[str, Any]], db_path: Path) -> dict[str, Any]:
    primary = primary_records(rows)
    head_research = build_head_research(primary)
    head_value_research = build_head_value_research(primary)
    strategy_research = build_strategy_research(primary)
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
        "head_research": head_research,
        "head_value_research": head_value_research,
        "strategy_research": strategy_research,
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
    write_head_research_db(db_path, summary["head_research"]["rows"])
    write_head_value_research_db(db_path, summary["head_value_research"]["rows"])
    write_strategy_research_db(db_path, summary["strategy_research"]["rows"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

    print(f"wrote {db_path}")
    print(f"wrote {summary_path}")
    print(f"snapshots={len(rows)} primary={summary['source']['primary_race_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
