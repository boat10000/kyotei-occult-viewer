#!/usr/bin/env python3
"""Generate a JSON prototype for manshu race ranking and boat roles."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


JST = timezone(timedelta(hours=9))
VERSION = "manshu-role-ranking-v1"


BUY_STYLE_1_GOOD_VENUES = {
    "02": "戸田",
    "04": "平和島",
    "11": "びわこ",
    "12": "住之江",
    "14": "鳴門",
    "15": "丸亀",
    "17": "宮島",
    "18": "徳山",
    "24": "大村",
}
BUY_STYLE_1_HOLD_VENUES = {"10": "三国"}
BUY_STYLE_1_AVOID_VENUES = {
    "03": "江戸川",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "13": "尼崎",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
}

BUY_STYLE_1_STATS = {
    "overall": {
        "races": 164,
        "avg_points": 9.0,
        "hit_rate": 0.1037,
        "manshu_hit_rate": 0.0488,
        "return_rate": 1.5077,
        "return_rate_without_max": 1.1115,
        "profit_yen_per_100": 74930,
        "max_drawdown_yen_per_100": 56190,
        "max_losing_streak": 32,
    },
    "good_venues": {
        "races": 62,
        "hit_rate": 0.1935,
        "manshu_hit_rate": 0.1129,
        "return_rate": 3.3486,
        "return_rate_without_max": 2.32,
        "validation_races": 18,
        "validation_return_rate": 4.0728,
    },
}


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "") or pd.isna(value):
            return None
        output = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(output):
        return None
    return round(output, 3)


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, "") or pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_id(value: Any) -> str:
    if value in (None, "") or pd.isna(value):
        return ""
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def safe_text(value: Any) -> str | None:
    if value in (None, "") or pd.isna(value):
        return None
    return str(value)


def role_score(row: pd.Series, mode: str, role: str) -> float | None:
    if role == "head":
        return safe_float(row.get(f"head_score_{mode}"))
    if role == "axis":
        return safe_float(row.get(f"axis_score_{mode}"))
    if role == "toss":
        return safe_float(row.get(f"toss_score_{mode}"))
    return safe_float(row.get("strength_score"))


def probability_proxy(score: float | None, low: float, span: float) -> float | None:
    if score is None:
        return None
    # Transparent proxy for sorting/display. This is not a calibrated betting probability.
    value = low + (max(0.0, min(100.0, score)) / 100.0) * span
    return round(value, 4)


def formation_points(roles: dict[str, list[int]], name: str) -> int:
    return len(formation_combos(roles, name))


def formation_combos(roles: dict[str, list[int]], name: str) -> set[tuple[int, int, int]]:
    heads = roles.get("head", [])
    axes = roles.get("axis", [])
    toss = set(roles.get("toss", []))
    opponent = roles.get("opponent", [])
    no_toss = [lane for lane in heads + axes + opponent if lane not in toss]
    combos: set[tuple[int, int, int]] = set()
    if name == "A":
        first, second, third = heads, no_toss, no_toss
    elif name == "B":
        first, second, third = heads, axes + opponent, no_toss
    elif name == "C":
        first, second, third = heads, axes, no_toss
    elif name == "D":
        first, second, third = heads[:1], heads[1:] + axes, no_toss
    else:
        return set()
    output: set[tuple[int, int, int]] = set()
    for a in first:
        for b in second:
            for c in third:
                if len({a, b, c}) == 3 and not toss.intersection({a, b, c}):
                    output.add((a, b, c))
    return output


def lane_value(group: pd.DataFrame, lane: int, column: str) -> float | None:
    rows = group[group["lane"].astype(int) == lane]
    if rows.empty:
        return None
    return safe_float(rows.iloc[0].get(column))


def buy_style_1_venue_tier(jcd: str) -> dict[str, Any]:
    if jcd in BUY_STYLE_1_GOOD_VENUES:
        return {
            "tier": "good",
            "label": "相性良",
            "reason": "前半選定場で後半検証もプラス。買い方1の検証上は優先候補。",
        }
    if jcd in BUY_STYLE_1_HOLD_VENUES:
        return {
            "tier": "hold",
            "label": "保留",
            "reason": "全期間では良いが前半選定場ではないため、前向き検証待ち。",
        }
    if jcd in BUY_STYLE_1_AVOID_VENUES:
        return {
            "tier": "avoid",
            "label": "見送り寄り",
            "reason": "今回の買い方1検証では0回収や低回収が目立つ場。",
        }
    return {
        "tier": "neutral",
        "label": "中立",
        "reason": "場別サンプルが薄いため、全体条件だけで参考表示。",
    }


def buy_style_1_strategy(row: pd.Series, group: pd.DataFrame, roles: dict[str, list[int]]) -> dict[str, Any]:
    jcd = safe_id(row.get("jcd")).zfill(2)
    venue = buy_style_1_venue_tier(jcd)
    lane1_win = lane_value(group, 1, "national_win_rate")
    outer_wins = [lane_value(group, lane, "national_win_rate") for lane in (4, 5, 6)]
    outer_wins = [value for value in outer_wins if value is not None]
    lane1_vs_best_outer = lane1_win - max(outer_wins) if lane1_win is not None and outer_wins else None
    national_range = safe_float(row.get("national_win_range"))
    fixed_entry = bool(safe_int(row.get("fixed_entry")) or 0)
    outer_exhibition_top = bool(safe_int(row.get("outer_exhibition_top_flag")) or 0)
    conditions = {
        "lane1_national_win_rate_lt_5": lane1_win is not None and lane1_win < 5.0,
        "lane1_weaker_than_best_outer": lane1_vs_best_outer is not None and lane1_vs_best_outer < 0,
        "national_win_range_le_1_5": national_range is not None and national_range <= 1.5,
        "not_fixed_entry": not fixed_entry,
        "outer_exhibition_top": outer_exhibition_top,
    }
    condition_matched = all(conditions.values())
    tickets = sorted("-".join(str(value) for value in combo) for combo in formation_combos(roles, "D"))
    result_trifecta = safe_text(row.get("result_trifecta"))
    payout_yen = safe_int(row.get("payout_yen"))
    hit = result_trifecta in tickets if result_trifecta else None
    status = "candidate" if condition_matched and venue["tier"] == "good" else "watch" if condition_matched else "outside_rule"
    if condition_matched and venue["tier"] == "avoid":
        status = "avoid"
    elif condition_matched and venue["tier"] in {"hold", "neutral"}:
        status = "hold"
    return {
        "version": "buy-style-1-v1",
        "label": "買い方1（検証用9点）",
        "condition_matched": condition_matched,
        "status": status,
        "status_label": {
            "candidate": "相性良・条件一致",
            "hold": "条件一致・保留",
            "avoid": "条件一致・見送り寄り",
            "outside_rule": "条件外",
        }[status],
        "venue_tier": venue["tier"],
        "venue_label": venue["label"],
        "venue_reason": venue["reason"],
        "conditions": conditions,
        "metrics": {
            "lane1_national_win_rate": lane1_win,
            "lane1_vs_best_outer_win_diff": round(lane1_vs_best_outer, 3) if lane1_vs_best_outer is not None else None,
            "national_win_range": national_range,
        },
        "formation": {
            "name": "D",
            "points": len(tickets),
            "definition": "頭1番手-頭2番手+軸2艇-消し以外",
            "tickets": tickets,
        },
        "historical": BUY_STYLE_1_STATS,
        "result_check": {
            "hit": hit,
            "return_yen_per_100": payout_yen if hit else 0 if hit is not None else None,
            "manshu_hit": bool(hit and payout_yen is not None and payout_yen >= 10000) if hit is not None else None,
        },
        "notes": [
            "過去検証用の固定ルールです。舟券購入を推奨するものではありません。",
            "場別フィルタはサンプルが少ないため前向き検証が必要です。",
        ],
    }


def build_race(group: pd.DataFrame, mode: str) -> dict[str, Any]:
    row = group.iloc[0]
    role_col = f"role_{mode}"
    rank_col = f"role_rank_{mode}"
    roles: dict[str, list[int]] = {"head": [], "axis": [], "toss": [], "opponent": []}
    boats: list[dict[str, Any]] = []
    for _, boat in group.sort_values("lane").iterrows():
        role = safe_text(boat.get(role_col)) or "opponent"
        lane = int(boat["lane"])
        roles.setdefault(role, []).append(lane)
        boats.append(
            {
                "lane": lane,
                "registration_no": safe_id(boat.get("registration_no")),
                "name": safe_text(boat.get("name")),
                "class": safe_text(boat.get("class")),
                "role": role,
                "role_rank": safe_int(boat.get(rank_col)),
                "role_score": role_score(boat, mode, role),
                "role_reason": {
                    "head": safe_text(boat.get("head_reasons")),
                    "axis": safe_text(boat.get("axis_reasons")),
                    "toss": safe_text(boat.get("toss_reasons")),
                }.get(role, "相手候補"),
                "scores": {
                    "head": safe_float(boat.get(f"head_score_{mode}")),
                    "axis": safe_float(boat.get(f"axis_score_{mode}")),
                    "toss": safe_float(boat.get(f"toss_score_{mode}")),
                    "strength": safe_float(boat.get("strength_score")),
                    "start": safe_float(boat.get("start_score")),
                    "exhibition": safe_float(boat.get("exhibition_score")),
                    "outside_attack": safe_float(boat.get("outside_attack_score")),
                },
                "features": {
                    "national_win_rate": safe_float(boat.get("national_win_rate")),
                    "local_win_rate": safe_float(boat.get("local_win_rate")),
                    "avg_st": safe_float(boat.get("avg_st")),
                    "motor_quinella_rate": safe_float(boat.get("motor_quinella_rate")),
                    "exhibition_time": safe_float(boat.get("exhibition_time")),
                    "exhibition_rank": safe_int(boat.get("exhibition_rank")),
                },
            }
        )
    for key in roles:
        roles[key].sort()
    chaos = safe_float(row.get("chaos_score"))
    skip = bool(safe_int(row.get(f"skip_{mode}")) or 0)
    skip_reason = safe_text(row.get(f"skip_reason_{mode}")) or ""
    result_trifecta = safe_text(row.get("result_trifecta"))
    payout_yen = safe_int(row.get("payout_yen"))
    is_labeled = bool(safe_int(row.get("is_labeled")) or (result_trifecta and payout_yen is not None))
    manshu_flag = bool(safe_int(row.get("manshu_flag")) or (payout_yen is not None and payout_yen >= 10000))
    big_manshu_flag = bool(safe_int(row.get("big_manshu_flag")) or (payout_yen is not None and payout_yen >= 50000))
    return {
        "race_id": safe_text(row.get("race_id")),
        "date": safe_text(row.get("date")),
        "jcd": safe_id(row.get("jcd")).zfill(2),
        "venue_name": safe_text(row.get("venue_name")),
        "race_no": safe_int(row.get("race_no")),
        "race_name": safe_text(row.get("race_name")),
        "deadline": safe_text(row.get("deadline")),
        "grade": safe_text(row.get("grade")),
        "time_zone": safe_text(row.get("time_zone")),
        "scores": {
            "manshu_score": chaos,
            "manshu_probability_proxy": probability_proxy(chaos, 0.08, 0.24),
            "target_arare_probability_proxy": probability_proxy(chaos, 0.18, 0.35),
            "data_quality_score": safe_float(row.get("data_quality_score")),
        },
        "risk_flags": {
            "lane1_not_a1": bool(safe_int(row.get("lane1_not_a1")) or 0),
            "lane1_b_class": bool(safe_int(row.get("lane1_b_class")) or 0),
            "outer_a_count": safe_int(row.get("outer_a_count")),
            "outer_motor_strong": bool(safe_int(row.get("outer_motor_strong_flag")) or 0),
            "outer_exhibition_top": bool(safe_int(row.get("outer_exhibition_top_flag")) or 0),
            "national_win_range": safe_float(row.get("national_win_range")),
            "lane1_vs_avg_win_diff": safe_float(row.get("lane1_vs_avg_win_diff")),
            "wind_speed_m": safe_float(row.get("wind_speed_m")),
            "wave_cm": safe_float(row.get("wave_cm")),
        },
        "result": {
            "status": "confirmed" if is_labeled else "pending",
            "is_labeled": is_labeled,
            "trifecta": result_trifecta,
            "payout_yen": payout_yen,
            "manshu": manshu_flag if is_labeled else None,
            "big_manshu": big_manshu_flag if is_labeled else None,
        },
        "role_summary": roles,
        "boats": sorted(boats, key=lambda item: (item["role"], item["role_rank"] or 9, item["lane"])),
        "formations": {
            "A": {"points": formation_points(roles, "A"), "definition": "頭2艇-消し以外-消し以外"},
            "B": {"points": formation_points(roles, "B"), "definition": "頭2艇-軸2艇+相手-消し以外"},
            "C": {"points": formation_points(roles, "C"), "definition": "頭2艇-軸2艇-消し以外"},
            "D": {"points": formation_points(roles, "D"), "definition": "頭1番手-頭2番手+軸2艇-消し以外"},
        },
        "strategy": {
            "buy_style_1": buy_style_1_strategy(row, group, roles),
        },
        "skip_recommendation": {
            "skip": skip,
            "reasons": [part for part in skip_reason.split("|") if part],
        },
        "notes": [
            "娯楽・研究用の分析出力です。舟券購入を推奨するものではありません。",
            "確率は表示用の暫定proxyで、実測的中確率や利益を保証しません。",
        ],
    }


def run(args: argparse.Namespace) -> int:
    boats = pd.read_csv(args.dataset)
    date_text = args.date
    if date_text:
        boats = boats[boats["date"].astype(str) == date_text]
    if boats.empty:
        raise SystemExit(f"no rows for date={date_text}")
    races = [build_race(group, args.mode) for _, group in boats.groupby("race_id", sort=False)]
    races.sort(key=lambda item: (item["scores"]["manshu_score"] or -1), reverse=True)
    if args.top:
        races = races[: args.top]
    output = {
        "version": VERSION,
        "mode": args.mode,
        "date": date_text,
        "generated_at": datetime.now(JST).isoformat(),
        "source": {
            "dataset": args.source_dataset_label or args.dataset,
            "official": True,
            "notes": [
                "既存正規化データから生成したロール表示用JSONです。",
                "manshu.html は同日付の data/output/manshu_role_ranking_YYYYMMDD.json を読み込みます。",
            ],
        },
        "races": races,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"wrote {path} races={len(races)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/analysis/boat_role_dataset.csv")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--mode", choices=["morning", "preview"], default="preview")
    parser.add_argument("--top", type=int, default=24)
    parser.add_argument("--output", default="data/output/manshu_role_ranking_20260616.json")
    parser.add_argument("--source-dataset-label", help="public label for the dataset path stored in JSON")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
