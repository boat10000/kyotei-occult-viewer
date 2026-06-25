#!/usr/bin/env python3
"""Build the static history index for Codex manshu ranking result pages."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
RANKING_RE = re.compile(r"boaters_manshu_ranking_(\d{8})\.json$")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def date_from_key(key: str) -> str:
    return f"{key[:4]}-{key[4:6]}-{key[6:8]}"


def key_from_date(date_text: str) -> str:
    return date_text.replace("-", "")


def as_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def as_int(value: Any) -> int | None:
    number = as_num(value)
    return int(number) if number is not None else None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_of(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result") or {}
    payout = as_int(result.get("payout_yen"))
    if payout is None:
        payout = as_int(row.get("payout_yen") if row.get("payout_yen") is not None else row.get("payout"))
    trifecta = result.get("trifecta") or row.get("trifecta")
    return {"trifecta": trifecta, "payout_yen": payout, "manshu": bool(payout is not None and payout >= 10000)}


def race_label(row: dict[str, Any]) -> str:
    place = row.get("place_name") or ""
    round_no = row.get("round") if row.get("round") is not None else row.get("round_no")
    return f"{place}{round_no}R"


def parse_boat_list(value: Any) -> list[int]:
    boats: list[int] = []
    for part in re.split(r"[,\s、]+", str(value or "")):
        if part.isdigit():
            boat = int(part)
            if 1 <= boat <= 6 and boat not in boats:
                boats.append(boat)
    return boats


def boat_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = row.get("metrics") or {}
    source = metrics.get("boats")
    rows: list[dict[str, Any]] = []
    if isinstance(source, list) and source:
        for item in source:
            boat = as_int(item.get("boat_number"))
            if boat is None:
                continue
            rows.append(
                {
                    "boat": boat,
                    "win": as_num(item.get("composite_win_pct") if item.get("composite_win_pct") is not None else item.get("win_pct")),
                    "top3": as_num(item.get("composite_top3_pct") if item.get("composite_top3_pct") is not None else item.get("top3_pct")),
                    "general_top3": as_num(item.get("general_top3_pct")),
                    "ai_plus": as_num(item.get("ai_plus")),
                    "ai_plus_rank": as_int(item.get("ai_plus_rank")),
                }
            )
    if len(rows) < 6:
        by_boat = {item["boat"]: item for item in rows}
        for boat in range(1, 7):
            if boat in by_boat:
                continue
            rows.append(
                {
                    "boat": boat,
                    "win": as_num(metrics.get(f"boat{boat}_composite_win_pct") if metrics.get(f"boat{boat}_composite_win_pct") is not None else metrics.get(f"boat{boat}_ai_prediction_pct")),
                    "top3": as_num(metrics.get(f"boat{boat}_composite_top3_pct") if metrics.get(f"boat{boat}_composite_top3_pct") is not None else metrics.get(f"boat{boat}_ai_3ren_pct")),
                    "general_top3": as_num(metrics.get(f"boat{boat}_general_3ren_pct")),
                    "ai_plus": as_num(metrics.get(f"boat{boat}_ai_plus")),
                    "ai_plus_rank": as_int(metrics.get(f"boat{boat}_ai_plus_order")),
                }
            )
    return sorted(rows, key=lambda item: item["boat"])


def prediction_plan(row: dict[str, Any], max_points: int = 15) -> dict[str, Any]:
    metrics = row.get("metrics") or {}
    rows = boat_rows(row)
    by_boat = {item["boat"]: item for item in rows}

    def win_score(boat: int) -> float:
        return as_num(by_boat.get(boat, {}).get("win")) or 0.0

    def top3_score(boat: int) -> float:
        item = by_boat.get(boat, {})
        return as_num(item.get("top3")) or as_num(item.get("ai_plus")) or as_num(item.get("win")) or 0.0

    ai_ranked = [item for item in rows if as_int(item.get("ai_plus_rank")) is not None]
    if len(ai_ranked) >= 3:
        axis_primary = [
            item["boat"]
            for item in sorted(ai_ranked, key=lambda item: (as_int(item.get("ai_plus_rank")) or 99, item["boat"]))
            if item.get("ai_plus_rank") in {1, 3}
        ][:2]
        axis_alt = [
            item["boat"]
            for item in sorted(ai_ranked, key=lambda item: (as_int(item.get("ai_plus_rank")) or 99, item["boat"]))
            if item.get("ai_plus_rank") in {2, 3}
        ][:2]
        toss_items = [item for item in ai_ranked if item.get("ai_plus_rank") == 6]
        axis_source = "ai_plus_rank"
    else:
        scored = sorted(rows, key=lambda item: (top3_score(item["boat"]), win_score(item["boat"])), reverse=True)
        axis_primary = [item["boat"] for item in scored[:3:2]]
        axis_alt = [item["boat"] for item in scored[1:3]]
        toss_items = [scored[-1]] if scored else []
        axis_source = "fallback_ai_win_rank"

    while len(axis_primary) < 2:
        for item in sorted(rows, key=lambda item: top3_score(item["boat"]), reverse=True):
            if item["boat"] not in axis_primary:
                axis_primary.append(item["boat"])
                break
    while len(axis_alt) < 2:
        for item in sorted(rows, key=lambda item: top3_score(item["boat"]), reverse=True):
            if item["boat"] not in axis_alt:
                axis_alt.append(item["boat"])
                break

    toss = toss_items[0]["boat"] if toss_items else None
    longshot_heads = [boat for boat in parse_boat_list(metrics.get("longshot_head_boats")) if boat != toss]
    super_slit = set(parse_boat_list(metrics.get("super_slit_boats")))
    double_time = set(parse_boat_list(metrics.get("double_time_boats")))
    matchup_buff = set(parse_boat_list(metrics.get("matchup_buff_boats")))

    def head_score(boat: int) -> float:
        score = win_score(boat)
        if boat in super_slit:
            score += 3.0
        if boat in double_time:
            score += 2.5
        if boat in matchup_buff:
            score += 2.0
        if boat in {5, 6} and (as_num(metrics.get("outer56_best_avg_isshu_diff")) or -9) >= 0.14:
            score += 2.0
        if boat == 1:
            score -= 20.0
        return score

    heads: list[int] = []
    for boat in longshot_heads:
        if boat not in heads and boat != toss:
            heads.append(boat)
    for boat in sorted([3, 4, 5, 6], key=head_score, reverse=True):
        if boat not in heads and boat != toss:
            heads.append(boat)
        if len(heads) >= 2:
            break
    if len(heads) < 2:
        for boat in sorted([2, 3, 4, 5, 6], key=head_score, reverse=True):
            if boat not in heads and boat != toss:
                heads.append(boat)
            if len(heads) >= 2:
                break

    pool = [boat for boat in range(1, 7) if boat != toss]
    raw_tickets: set[str] = set()
    ticket_scores: dict[str, float] = {}
    for head in heads[:2]:
        for axis in axis_primary[:2]:
            if axis == head or axis == toss:
                continue
            for partner in pool:
                if partner in {head, axis}:
                    continue
                for combo in ((head, axis, partner), (head, partner, axis)):
                    ticket = "-".join(str(part) for part in combo)
                    raw_tickets.add(ticket)
                    ticket_scores[ticket] = (
                        head_score(head) * 2.0
                        + top3_score(axis)
                        + top3_score(partner) * 0.65
                        + (8.0 if partner in {5, 6} else 0.0)
                        + (4.0 if axis in {5, 6} else 0.0)
                    )

    tickets = sorted(raw_tickets, key=lambda ticket: ticket_scores.get(ticket, 0.0), reverse=True)[:max_points]
    result = result_of(row)
    hit = bool(result["trifecta"] and result["trifecta"] in tickets)
    result_boats = [int(part) for part in str(result["trifecta"] or "").split("-") if part.isdigit()]
    investment = len(tickets) * 100
    payout = result["payout_yen"] if hit and result["payout_yen"] is not None else 0
    return {
        "decision": "買い" if tickets else "見送り",
        "heads": heads[:2],
        "axis": axis_primary[:2],
        "axis_alt_2_3": axis_alt[:2],
        "toss": toss,
        "axis_source": axis_source,
        "tickets": tickets,
        "points": len(tickets),
        "hit": hit,
        "head_hit": bool(result_boats and result_boats[0] in heads[:2]),
        "axis_hit": bool(set(result_boats) & set(axis_primary[:2])),
        "axis_alt_hit": bool(set(result_boats) & set(axis_alt[:2])),
        "toss_came": bool(toss and toss in result_boats),
        "investment_yen": investment,
        "payout_yen": payout,
        "profit_yen": payout - investment if investment else 0,
        "data_warning": "AI+6艇不足のためAI1着率順で代替" if axis_source != "ai_plus_rank" else "",
    }


def strategy_stats(rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    picked = rows[:top_n]
    buy_races = hit_count = manshu_hit_count = head_hits = axis_hits = axis_alt_hits = toss_came = 0
    points = investment = payout = settled = 0
    max_payout = 0
    data_warning_count = 0
    for row in picked:
        result = result_of(row)
        if result["payout_yen"] is None:
            continue
        settled += 1
        plan = prediction_plan(row)
        if plan["decision"] != "買い":
            continue
        buy_races += 1
        points += plan["points"]
        investment += plan["investment_yen"]
        payout += plan["payout_yen"]
        max_payout = max(max_payout, plan["payout_yen"] or 0)
        hit_count += int(bool(plan["hit"]))
        manshu_hit_count += int(bool(plan["hit"] and result["manshu"]))
        head_hits += int(bool(plan["head_hit"]))
        axis_hits += int(bool(plan["axis_hit"]))
        axis_alt_hits += int(bool(plan["axis_alt_hit"]))
        toss_came += int(bool(plan["toss_came"]))
        data_warning_count += int(bool(plan["data_warning"]))
    return {
        "selected": len(picked),
        "settled": settled,
        "buy_races": buy_races,
        "total_points": points,
        "investment_yen": investment,
        "payout_yen": payout,
        "profit_yen": payout - investment,
        "roi_pct": round(payout / investment * 100, 2) if investment else None,
        "hit_count": hit_count,
        "hit_rate_pct": round(hit_count / buy_races * 100, 2) if buy_races else None,
        "manshu_hit_count": manshu_hit_count,
        "manshu_hit_rate_pct": round(manshu_hit_count / buy_races * 100, 2) if buy_races else None,
        "head_hit_count": head_hits,
        "head_hit_rate_pct": round(head_hits / buy_races * 100, 2) if buy_races else None,
        "axis_1_3_hit_count": axis_hits,
        "axis_1_3_hit_rate_pct": round(axis_hits / buy_races * 100, 2) if buy_races else None,
        "axis_2_3_hit_count": axis_alt_hits,
        "axis_2_3_hit_rate_pct": round(axis_alt_hits / buy_races * 100, 2) if buy_races else None,
        "toss_came_count": toss_came,
        "toss_came_rate_pct": round(toss_came / buy_races * 100, 2) if buy_races else None,
        "max_hit_payout_yen": max_payout or None,
        "data_warning_count": data_warning_count,
    }


def stats(rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    picked = rows[:top_n]
    settled = []
    hits = []
    max_payout = 0
    for row in picked:
        result = result_of(row)
        payout = result["payout_yen"]
        if payout is None:
            continue
        settled.append(row)
        max_payout = max(max_payout, payout)
        if result["manshu"]:
            hits.append(
                {
                    "rank": as_int(row.get("rank")),
                    "race": race_label(row),
                    "trifecta": result["trifecta"],
                    "payout_yen": payout,
                    "manshu_rate_pct": as_num(row.get("manshu_rate_pct")),
                }
            )
    return {
        "selected": len(picked),
        "settled": len(settled),
        "manshu_hits": len(hits),
        "manshu_rate_pct": round(len(hits) / len(settled) * 100, 2) if settled else None,
        "max_payout_yen": max_payout or None,
        "hit_races": hits,
    }


def aggregate(day_items: list[dict[str, Any]], group: str, key: str) -> dict[str, Any]:
    selected = settled = manshu_hits = hit_days = days_with_settled = 0
    max_payout = 0
    for item in day_items:
        stat = ((item.get(group) or {}).get(key)) or {}
        selected += as_int(stat.get("selected")) or 0
        settled_count = as_int(stat.get("settled")) or 0
        hit_count = as_int(stat.get("manshu_hits")) or 0
        settled += settled_count
        manshu_hits += hit_count
        if settled_count:
            days_with_settled += 1
        if hit_count:
            hit_days += 1
        payout = as_int(stat.get("max_payout_yen")) or 0
        max_payout = max(max_payout, payout)
    return {
        "selected": selected,
        "settled": settled,
        "manshu_hits": manshu_hits,
        "manshu_rate_pct": round(manshu_hits / settled * 100, 2) if settled else None,
        "hit_days": hit_days,
        "days": days_with_settled,
        "calendar_days": len(day_items),
        "day_hit_rate_pct": round(hit_days / days_with_settled * 100, 2) if days_with_settled else None,
        "max_payout_yen": max_payout or None,
    }


def aggregate_strategy(day_items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    selected = settled = buy_races = points = investment = payout = hit_count = manshu_hit_count = 0
    head_hits = axis_hits = axis_alt_hits = toss_came = warning_count = 0
    hit_days = active_days = 0
    max_payout = 0
    for item in day_items:
        stat = ((item.get("strategy") or {}).get(key)) or {}
        selected += as_int(stat.get("selected")) or 0
        settled += as_int(stat.get("settled")) or 0
        buys = as_int(stat.get("buy_races")) or 0
        buy_races += buys
        points += as_int(stat.get("total_points")) or 0
        investment += as_int(stat.get("investment_yen")) or 0
        payout += as_int(stat.get("payout_yen")) or 0
        hit_count += as_int(stat.get("hit_count")) or 0
        manshu_hit_count += as_int(stat.get("manshu_hit_count")) or 0
        head_hits += as_int(stat.get("head_hit_count")) or 0
        axis_hits += as_int(stat.get("axis_1_3_hit_count")) or 0
        axis_alt_hits += as_int(stat.get("axis_2_3_hit_count")) or 0
        toss_came += as_int(stat.get("toss_came_count")) or 0
        warning_count += as_int(stat.get("data_warning_count")) or 0
        max_payout = max(max_payout, as_int(stat.get("max_hit_payout_yen")) or 0)
        if buys:
            active_days += 1
        if as_int(stat.get("hit_count")):
            hit_days += 1
    return {
        "selected": selected,
        "settled": settled,
        "buy_races": buy_races,
        "total_points": points,
        "investment_yen": investment,
        "payout_yen": payout,
        "profit_yen": payout - investment,
        "roi_pct": round(payout / investment * 100, 2) if investment else None,
        "hit_count": hit_count,
        "hit_rate_pct": round(hit_count / buy_races * 100, 2) if buy_races else None,
        "manshu_hit_count": manshu_hit_count,
        "manshu_hit_rate_pct": round(manshu_hit_count / buy_races * 100, 2) if buy_races else None,
        "head_hit_count": head_hits,
        "head_hit_rate_pct": round(head_hits / buy_races * 100, 2) if buy_races else None,
        "axis_1_3_hit_count": axis_hits,
        "axis_1_3_hit_rate_pct": round(axis_hits / buy_races * 100, 2) if buy_races else None,
        "axis_2_3_hit_count": axis_alt_hits,
        "axis_2_3_hit_rate_pct": round(axis_alt_hits / buy_races * 100, 2) if buy_races else None,
        "toss_came_count": toss_came,
        "toss_came_rate_pct": round(toss_came / buy_races * 100, 2) if buy_races else None,
        "hit_days": hit_days,
        "active_days": active_days,
        "day_hit_rate_pct": round(hit_days / active_days * 100, 2) if active_days else None,
        "max_hit_payout_yen": max_payout or None,
        "data_warning_count": warning_count,
    }


def pick_payload_path(key: str) -> Path | None:
    codex_path = OUTPUT_DIR / f"boaters_manshu_ranking_codex_{key}.json"
    normal_path = OUTPUT_DIR / f"boaters_manshu_ranking_{key}.json"
    if codex_path.exists():
        return codex_path
    if normal_path.exists():
        return normal_path
    return None


def ranking_paths() -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for path in sorted(OUTPUT_DIR.glob("boaters_manshu_ranking_*.json")):
        if path.name.startswith("boaters_manshu_ranking_codex_"):
            continue
        match = RANKING_RE.match(path.name)
        if not match:
            continue
        key = match.group(1)
        payload_path = pick_payload_path(key)
        if payload_path:
            items.append((key, payload_path))
    return items


def build(start_date: str | None, end_date: str | None, top_n: int) -> dict[str, Any]:
    start_key = key_from_date(start_date) if start_date else None
    end_key = key_from_date(end_date) if end_date else None
    dates: list[dict[str, Any]] = []
    for key, payload_path in ranking_paths():
        if start_key and key < start_key:
            continue
        if end_key and key > end_key:
            continue
        payload = load_json(payload_path)
        races = list(payload.get("races") or [])
        strict_value = payload.get("strict_races")
        strict_races = list(strict_value) if isinstance(strict_value, list) else []
        strict_is_fallback = False
        if not strict_races:
            row_types = {str(row.get("ranking_type") or "").strip() for row in races}
            row_statuses = {str(row.get("status") or "").strip() for row in races}
            if row_types == {"strict"} or row_statuses <= {"展示待ち", "確定", "厳選統合", "厳選統合・展示待ち"}:
                strict_races = races
                strict_is_fallback = True
        date_text = payload.get("date") or date_from_key(key)
        item = {
            "date": date_text,
            "key": key,
            "path": f"data/output/boaters_manshu_ranking_{key}.json",
            "codex_path": f"data/output/{payload_path.name}" if payload_path.name.startswith("boaters_manshu_ranking_codex_") else "",
            "logic_label": payload.get("logic_label"),
            "generated_at": payload.get("generated_at"),
            "all_venue": {
                "top1": stats(races, 1),
                "top3": stats(races, 3),
                "top5": stats(races, 5),
                "top10": stats(races, top_n),
            },
            "strict": {
                "top1": stats(strict_races, 1),
                "top3": stats(strict_races, 3),
                "top5": stats(strict_races, 5),
                "top10": stats(strict_races, top_n),
                "fallback_from_all_venue": strict_is_fallback,
            },
            "strategy": {
                "top1": strategy_stats(strict_races, 1),
                "top3": strategy_stats(strict_races, 3),
                "top5": strategy_stats(strict_races, 5),
                "top10": strategy_stats(strict_races, top_n),
            },
        }
        dates.append(item)
    dates.sort(key=lambda item: item["date"])
    aggregate_data = {
        "all_venue": {key: aggregate(dates, "all_venue", key) for key in ["top1", "top3", "top5", "top10"]},
        "strict": {key: aggregate(dates, "strict", key) for key in ["top1", "top3", "top5", "top10"]},
        "strategy": {key: aggregate_strategy(dates, key) for key in ["top1", "top3", "top5", "top10"]},
    }
    return {
        "version": "boaters-manshu-history-index-v4",
        "generated_at": iso_now(),
        "start_date": dates[0]["date"] if dates else start_date,
        "end_date": dates[-1]["date"] if dates else end_date,
        "top_n": top_n,
        "logic_label": "Codex厳選ランキング（全ファクター統合）結果集計",
        "dates": dates,
        "aggregate": aggregate_data,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2026-05-01")
    parser.add_argument("--end-date")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--out", default=str(OUTPUT_DIR / "boaters_manshu_history_index.json"))
    args = parser.parse_args()
    payload = build(args.start_date, args.end_date, args.top_n)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out_path),
                "start_date": payload.get("start_date"),
                "end_date": payload.get("end_date"),
                "dates": len(payload.get("dates") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
