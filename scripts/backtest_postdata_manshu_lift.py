#!/usr/bin/env python3
"""Backtest post-AI/exhibition lift signals on the morning watchlist."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from monitor_boaters_manshu_alerts import super_arunashi3  # noqa: E402
from rank_daily_manshu_candidates import (  # noqa: E402
    all_venue_edge_signals,
    build_morning_candidates,
    daily_features,
    int_num,
    num,
)


POST_IDS = {
    "codex_post_ai_exh_outer56_ai10_aiplus100_isshu2",
    "codex_post_ai_exh_b1aipred30_outer10_rank6exh",
    "codex_post_ai_exh_b1aipred30_outeraiplus1_superslit",
    "codex_post_ai_exh_outer56_ai12_avg010_outerdouble",
    "codex_post_ai_exh_b1aipred30_outer56_ai12_outerdouble",
    "codex_post_ai_exh_outer56_ai10_outerhead_b1avg0",
    "codex_post_ai_exh_rank6_outer_ai5_outertenji2",
    "codex_post_ai_exh_rank6_outer_ai5_rank6exh",
}

STRONG_IDS = {
    "codex_post_ai_exh_outer56_ai12_avg010_outerdouble",
    "codex_post_ai_exh_b1aipred30_outer56_ai12_outerdouble",
    "codex_post_ai_exh_outer56_ai10_outerhead_b1avg0",
    "codex_post_ai_exh_rank6_outer_ai5_rank6exh",
}

STABLE_IDS = {
    "codex_post_ai_exh_outer56_ai10_aiplus100_isshu2",
    "codex_post_ai_exh_b1aipred30_outer10_rank6exh",
    "codex_post_ai_exh_b1aipred30_outeraiplus1_superslit",
}


def as_bool(value) -> bool:
    return bool(int_num(value))


def dates_from_db(db_path: Path, start: str | None, end: str | None) -> list[str]:
    clauses = ["result_payout3t1 IS NOT NULL"]
    params: list[str] = []
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    sql = f"SELECT DISTINCT date FROM races WHERE {' AND '.join(clauses)} ORDER BY date"
    with sqlite3.connect(db_path) as con:
        return [row[0] for row in con.execute(sql, params)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return center - half, center + half


def summarize(rows: pd.DataFrame, segment: str, mask: pd.Series, baseline_rate: float) -> dict:
    sub = rows[mask.fillna(False)]
    n = int(len(sub))
    manshu = int(sub["is_manshu"].sum()) if n else 0
    rate = manshu / n if n else None
    ci_low, ci_high = wilson(manshu, n)
    return {
        "segment": segment,
        "races": n,
        "manshu": manshu,
        "manshu_rate_pct": round(rate * 100, 2) if rate is not None else None,
        "baseline_pct": round(baseline_rate * 100, 2),
        "lift_vs_morning_top5": round(rate / baseline_rate, 2) if rate is not None and baseline_rate else None,
        "ci95_low": round(ci_low * 100, 2) if ci_low is not None else None,
        "ci95_high": round(ci_high * 100, 2) if ci_high is not None else None,
    }


def ticket_hit(tickets: set[str], trifecta) -> bool:
    combo = "".join(ch for ch in str(trifecta or "") if ch.isdigit())
    return len(combo) == 3 and combo in tickets


def metric_row(race: dict, boat: int) -> dict:
    tenji_rank = num(race.get(f"b{boat}_tenji_rank"))
    tenji_time_rank = num(race.get(f"b{boat}_tenji_time_rank"))
    exhibit_rank = min([v for v in [tenji_rank, tenji_time_rank] if v is not None], default=9)
    isshu_rank = num(race.get(f"b{boat}_isshu_rank"))
    double_time = as_bool(race.get(f"b{boat}_double_time"))
    return {
        "boat_number": boat,
        "ai_prediction_pct": num(race.get(f"b{boat}_ai_prediction_pct")),
        "ai_3ren_pct": num(race.get(f"b{boat}_ai_3ren_pct")),
        "general_3ren_pct": num(race.get(f"b{boat}_general_3ren_pct")),
        "ai_plus": num(race.get(f"b{boat}_ai_plus")),
        "ai_plus_rank": num(race.get(f"b{boat}_ai_plus_order")),
        "avg_isshu_diff": num(race.get(f"b{boat}_avg_isshu_diff")),
        "st_rank_general": num(race.get(f"b{boat}_st_rank_general")),
        "tenji_rank": tenji_rank,
        "tenji_time_rank": tenji_time_rank,
        "isshu_rank": isshu_rank,
        "exhibit_rank": exhibit_rank,
        "double_time": double_time,
        "super_slit_alert": as_bool(race.get(f"b{boat}_super_slit_alert")),
        "low_outer_revive": int_num(race.get("low_outer_boat")) == boat
        and as_bool(race.get("low_outer_exhibit_top2")),
        "summer_b1_score_bonus": 0,
        "super_slit_score_bonus": 4 if as_bool(race.get(f"b{boat}_super_slit_alert")) else 0,
        "matchup_score_bonus": 0,
    }


def ticket_payload(race: dict) -> tuple[set[str], dict | None]:
    rows = [metric_row(race, boat) for boat in range(1, 7)]
    return super_arunashi3(rows)


def roi_summary(rows: pd.DataFrame, segment: str, mask: pd.Series) -> dict:
    sub = rows[mask.fillna(False) & rows["ticket_count"].gt(0)]
    races = int(len(sub))
    points = int(sub["ticket_count"].sum()) if races else 0
    stake = points * 100
    hit_mask = sub["ticket_hit"].fillna(False).astype(bool)
    hits = int(hit_mask.sum()) if races else 0
    payback = int(sub.loc[hit_mask, "payout"].fillna(0).sum()) if hits else 0
    manshu_hits = int((hit_mask & sub["is_manshu"].astype(bool)).sum()) if races else 0
    return {
        "segment": segment,
        "buy_races": races,
        "total_points": points,
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": round(payback / stake * 100, 2) if stake else None,
        "hit_rate_pct": round(hits / races * 100, 2) if races else None,
        "manshu_hit_rate_pct": round(manshu_hits / races * 100, 2) if races else None,
        "avg_points": round(points / races, 2) if races else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/Users/ohyabumasaya/Desktop/price_action_analysis/outputs/boaters_all_races.sqlite")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-06-18")
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "postdata_manshu_backtest"))
    parser.add_argument("--progress-every", type=int, default=250)
    args = parser.parse_args()

    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)
    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dates = dates_from_db(db_path, args.start, args.end)
    rows: list[dict] = []
    started = time.time()

    for i, date_text in enumerate(dates, start=1):
        df = daily_features(db_path, date_text, {})
        if df.empty:
            continue
        candidates = build_morning_candidates(df, 5)
        race_map = {str(row["race_id"]): row for row in df.to_dict("records")}
        for candidate in candidates:
            race = race_map.get(str(candidate.get("race_id")))
            if not race:
                continue
            signals = all_venue_edge_signals(race)
            signal_ids = [signal["id"] for signal in signals]
            post_ids = [signal_id for signal_id in signal_ids if signal_id in POST_IDS]
            strong_ids = [signal_id for signal_id in post_ids if signal_id in STRONG_IDS]
            stable_ids = [signal_id for signal_id in post_ids if signal_id in STABLE_IDS]
            tickets, roles = ticket_payload(race)
            rank_value = int(candidate.get("rank") or len(rows) % 5 + 1)
            round_value = int_num(race.get("round_no"))
            post_core = (
                (
                    "codex_post_ai_exh_b1aipred30_outer56_ai12_outerdouble" in post_ids
                    and rank_value <= 3
                )
                or (
                    "codex_post_ai_exh_b1aipred30_outeraiplus1_superslit" in post_ids
                    and rank_value <= 3
                    and (round_value or 0) <= 6
                )
            )
            rows.append(
                {
                    "date": date_text,
                    "year": date_text[:4],
                    "rank": rank_value,
                    "place_name": race.get("place_name"),
                    "round": round_value,
                    "race_id": race.get("race_id"),
                    "payout": num(race.get("payout")),
                    "trifecta": race.get("trifecta"),
                    "is_manshu": int((num(race.get("payout")) or 0) >= 10000),
                    "candidate_score": candidate.get("candidate_score"),
                    "full_ai": int(
                        sum(1 for boat in range(1, 7) if num(race.get(f"b{boat}_ai_prediction_pct")) is not None) == 6
                    ),
                    "full_exh": int((int_num(race.get("tenji_boats")) or 0) >= 6 and (int_num(race.get("isshu_boats")) or 0) >= 6),
                    "post_any": int(bool(post_ids)),
                    "post_strong": int(bool(strong_ids)),
                    "post_stable": int(bool(stable_ids)),
                    "post_core": int(post_core),
                    "rank6_revive": int(any("rank6_outer" in signal_id for signal_id in post_ids)),
                    "post_signal_ids": "|".join(post_ids),
                    "post_strong_ids": "|".join(strong_ids),
                    "post_stable_ids": "|".join(stable_ids),
                    "top_signal_labels": " / ".join(signal["label"] for signal in signals[:5]),
                    "ticket_count": len(tickets),
                    "ticket_hit": int(ticket_hit(tickets, race.get("trifecta"))),
                    "tickets": " ".join(sorted(tickets)),
                    "heads": ",".join(map(str, (roles or {}).get("heads") or [])),
                    "axes": ",".join(map(str, (roles or {}).get("axes") or [])),
                    "keshi": (roles or {}).get("keshi"),
                }
            )
        if args.progress_every and i % args.progress_every == 0:
            print(f"progress {i}/{len(dates)} elapsed={time.time() - started:.1f}s", flush=True)

    result = pd.DataFrame(rows)
    if result.empty:
        raise SystemExit("no rows")
    baseline_rate = result["is_manshu"].mean()

    segment_defs = [
        ("朝TOP5全体", pd.Series(True, index=result.index)),
        ("AI6艇あり", result["full_ai"].eq(1)),
        ("展示+1周6艇あり", result["full_exh"].eq(1)),
        ("直前上げあり", result["post_any"].eq(1)),
        ("直前強上げあり", result["post_strong"].eq(1)),
        ("直前安定候補あり", result["post_stable"].eq(1)),
        ("直前本命条件あり", result["post_core"].eq(1)),
        ("AI+最下位5/6復活あり", result["rank6_revive"].eq(1)),
        ("直前上げなし", result["post_any"].eq(0)),
    ]
    summary = pd.DataFrame([summarize(result, name, mask, baseline_rate) for name, mask in segment_defs])

    condition_rows = []
    for signal_id in sorted(POST_IDS):
        mask = result["post_signal_ids"].str.contains(signal_id, regex=False, na=False)
        condition_rows.append(summarize(result, signal_id, mask, baseline_rate))
    condition_summary = pd.DataFrame(condition_rows).sort_values(["manshu_rate_pct", "races"], ascending=[False, False])

    by_year = (
        result.groupby(["year", "post_any"], dropna=False)
        .agg(races=("is_manshu", "size"), manshu=("is_manshu", "sum"))
        .reset_index()
    )
    by_year["manshu_rate_pct"] = (by_year["manshu"] / by_year["races"] * 100).round(2)

    roi = pd.DataFrame([roi_summary(result, name, mask) for name, mask in segment_defs])

    result.to_csv(out_dir / "postdata_backtest_picks.csv", index=False)
    summary.to_csv(out_dir / "postdata_backtest_summary.csv", index=False)
    condition_summary.to_csv(out_dir / "postdata_backtest_conditions.csv", index=False)
    by_year.to_csv(out_dir / "postdata_backtest_by_year.csv", index=False)
    roi.to_csv(out_dir / "postdata_backtest_roi.csv", index=False)
    manifest = {
        "source_db": str(db_path),
        "date_start": args.start,
        "date_end": args.end,
        "days": len(dates),
        "morning_top5_races": int(len(result)),
        "morning_top5_manshu_rate_pct": round(baseline_rate * 100, 2),
        "outputs": {
            "picks": str(out_dir / "postdata_backtest_picks.csv"),
            "summary": str(out_dir / "postdata_backtest_summary.csv"),
            "conditions": str(out_dir / "postdata_backtest_conditions.csv"),
            "by_year": str(out_dir / "postdata_backtest_by_year.csv"),
            "roi": str(out_dir / "postdata_backtest_roi.csv"),
        },
        "elapsed_sec": round(time.time() - started, 1),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("\n--- summary ---")
    print(summary.to_string(index=False))
    print("\n--- condition summary ---")
    print(condition_summary.to_string(index=False))
    print("\n--- roi ---")
    print(roi.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
