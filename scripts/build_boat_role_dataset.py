#!/usr/bin/env python3
"""Build a one-row-per-boat role dataset from race_dataset.csv.

The scoring rules are intentionally transparent and conservative. They do not
use result, payout, popularity, decision, actual course, or actual ST fields as
features. Result fields are kept only as labels for validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


Row = dict[str, Any]


ROLE_VERSION = "manshu-role-v1"


LANE1_PROFILE_COLUMNS = [
    "lane1_profile_starts",
    "lane1_profile_win_rate",
    "lane1_profile_miss_win_rate",
    "lane1_profile_top3_rate",
    "lane1_profile_out_top3_rate",
    "lane1_profile_teppan_score",
    "lane1_profile_tobi_score",
    "lane1_profile_manshu_rate_when_missed",
    "lane1_profile_label",
]

MATCHUP_PROFILE_COLUMNS = [
    "matchup_total_meetings",
    "matchup_opponents_seen",
    "matchup_coverage",
    "matchup_win_rate",
    "matchup_top3_rate",
    "matchup_ahead_rate",
    "matchup_lane1_meetings",
    "matchup_lane1_win_rate",
    "matchup_lane1_top3_rate",
    "matchup_lane1_ahead_rate",
    "matchup_head_bonus",
    "matchup_axis_bonus",
    "matchup_toss_bonus",
    "matchup_label",
]

MATCHUP_RACE_COLUMNS = [
    "matchup_lane1_pressure_score",
    "matchup_outer_good_count",
    "matchup_lane1_bad_flag",
    "matchup_notes",
]


def as_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "－"):
            return None
        output = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(output):
        return None
    return output


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "-", "－"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def scale(value: float | None, low: float, high: float, default: float = 50.0, invert: bool = False) -> float:
    if value is None:
        return default
    if high == low:
        return default
    scaled = (value - low) / (high - low) * 100.0
    if invert:
        scaled = 100.0 - scaled
    return clamp(scaled)


def bool_int(value: bool) -> int:
    return 1 if value else 0


def read_rows(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_registration_no(value: Any) -> str:
    if value in (None, "", "-", "－"):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(4) if text.isdigit() else text


def read_lane1_profiles(path: Path | None) -> dict[str, Row]:
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        profiles = {
            normalize_registration_no(row.get("registration_no")): row
            for row in csv.DictReader(handle)
        }
    profiles.pop("", None)
    return profiles


def read_matchup_profiles(path: Path | None) -> dict[tuple[str, str], Row]:
    if path is None or not path.exists():
        return {}
    profiles: dict[tuple[str, str], Row] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            racer = normalize_registration_no(row.get("racer_registration_no"))
            opponent = normalize_registration_no(row.get("opponent_registration_no"))
            if racer and opponent:
                profiles[(racer, opponent)] = row
    return profiles


def lane1_profile_for_race(race: Row, profiles: dict[str, Row]) -> Row | None:
    registration_no = normalize_registration_no(race.get("lane1_registration_no"))
    return profiles.get(registration_no)


def lane1_profile_label(profile: Row | None) -> str | None:
    if not profile:
        return None
    starts = as_int(profile.get("lane1_starts"))
    if starts < 10:
        return "データ薄め"
    tobi = as_float(profile.get("tobi_score"))
    teppan = as_float(profile.get("teppan_score"))
    miss_win = as_float(profile.get("lane1_miss_win_rate"))
    out_top3 = as_float(profile.get("lane1_out_top3_rate"))
    win = as_float(profile.get("lane1_win_rate"))
    top3 = as_float(profile.get("lane1_top3_rate"))
    if starts >= 15 and (
        (tobi is not None and tobi >= 0.30)
        or (miss_win is not None and miss_win >= 0.72)
        or (out_top3 is not None and out_top3 >= 0.34)
    ):
        return "イン飛び注意"
    if starts >= 15 and (
        (teppan is not None and teppan >= 0.72)
        or (
            win is not None
            and top3 is not None
            and win >= 0.82
            and top3 >= 0.90
        )
    ):
        return "イン鉄板寄り"
    return "標準"


def lane1_profile_metrics(profile: Row | None) -> Row:
    if not profile:
        return {key: None for key in LANE1_PROFILE_COLUMNS}
    return {
        "lane1_profile_starts": as_int(profile.get("lane1_starts")) or None,
        "lane1_profile_win_rate": as_float(profile.get("lane1_win_rate")),
        "lane1_profile_miss_win_rate": as_float(profile.get("lane1_miss_win_rate")),
        "lane1_profile_top3_rate": as_float(profile.get("lane1_top3_rate")),
        "lane1_profile_out_top3_rate": as_float(profile.get("lane1_out_top3_rate")),
        "lane1_profile_teppan_score": as_float(profile.get("teppan_score")),
        "lane1_profile_tobi_score": as_float(profile.get("tobi_score")),
        "lane1_profile_manshu_rate_when_missed": as_float(profile.get("manshu_rate_when_lane1_missed")),
        "lane1_profile_label": lane1_profile_label(profile),
    }


def empty_matchup_metrics() -> Row:
    return {
        "matchup_total_meetings": None,
        "matchup_opponents_seen": 0,
        "matchup_coverage": 0.0,
        "matchup_win_rate": None,
        "matchup_top3_rate": None,
        "matchup_ahead_rate": None,
        "matchup_lane1_meetings": None,
        "matchup_lane1_win_rate": None,
        "matchup_lane1_top3_rate": None,
        "matchup_lane1_ahead_rate": None,
        "matchup_head_bonus": 0.0,
        "matchup_axis_bonus": 0.0,
        "matchup_toss_bonus": 0.0,
        "matchup_label": "相性データ薄",
    }


def matchup_rate(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def build_matchup_context(race: Row, profiles: dict[tuple[str, str], Row]) -> tuple[dict[int, Row], Row]:
    if not profiles:
        return ({lane: empty_matchup_metrics() for lane in range(1, 7)}, {key: None for key in MATCHUP_RACE_COLUMNS})

    regs = {
        lane: normalize_registration_no(race.get(f"lane{lane}_registration_no"))
        for lane in range(1, 7)
    }
    metrics_by_lane: dict[int, Row] = {}
    lane1_reg = regs.get(1, "")
    pressure_score = 0.0
    outer_good_count = 0
    notes: list[str] = []

    for lane, reg in regs.items():
        if not reg:
            metrics_by_lane[lane] = empty_matchup_metrics()
            continue
        total = wins = top3 = ahead = 0
        opponents_seen = 0
        lane1_meetings = lane1_wins = lane1_top3 = lane1_ahead = 0
        for opponent_lane, opponent_reg in regs.items():
            if opponent_lane == lane or not opponent_reg:
                continue
            pair = profiles.get((reg, opponent_reg))
            if not pair:
                continue
            meetings = as_int(pair.get("meetings"))
            if meetings <= 0:
                continue
            total += meetings
            wins += as_int(pair.get("wins"))
            top3 += as_int(pair.get("top3"))
            ahead += as_int(pair.get("ahead"))
            if meetings >= 3:
                opponents_seen += 1
            if opponent_lane == 1:
                lane1_meetings += meetings
                lane1_wins += as_int(pair.get("wins_when_opponent_lane1"))
                lane1_top3 += as_int(pair.get("top3_when_opponent_lane1"))
                lane1_ahead += as_int(pair.get("ahead_when_opponent_lane1"))

        if total <= 0:
            metrics_by_lane[lane] = empty_matchup_metrics()
            continue

        win_rate = matchup_rate(wins, total)
        top3_rate = matchup_rate(top3, total)
        ahead_rate = matchup_rate(ahead, total)
        lane1_win_rate = matchup_rate(lane1_wins, lane1_meetings)
        lane1_top3_rate = matchup_rate(lane1_top3, lane1_meetings)
        lane1_ahead_rate = matchup_rate(lane1_ahead, lane1_meetings)
        reliability = min(1.0, total / 30.0) * min(1.0, max(opponents_seen, 1) / 3.0)
        lane1_reliability = min(1.0, lane1_meetings / 10.0)
        head_bonus = 0.0
        axis_bonus = 0.0
        toss_bonus = 0.0

        if total >= 8:
            if win_rate is not None and win_rate >= 0.16:
                head_bonus += min(5.0, (win_rate - 0.12) * 36.0) * reliability
            if ahead_rate is not None and ahead_rate >= 0.56:
                head_bonus += min(4.0, (ahead_rate - 0.52) * 22.0) * reliability
                axis_bonus += min(3.0, (ahead_rate - 0.52) * 16.0) * reliability
            if top3_rate is not None and top3_rate >= 0.54:
                axis_bonus += min(5.0, (top3_rate - 0.48) * 22.0) * reliability
            if top3_rate is not None and ahead_rate is not None and top3_rate <= 0.34 and ahead_rate <= 0.44:
                toss_bonus += min(6.0, (0.38 - top3_rate) * 18.0 + (0.48 - ahead_rate) * 12.0) * reliability

        if lane != 1 and lane1_reg and lane1_meetings >= 3:
            if lane1_ahead_rate is not None and lane1_ahead_rate >= 0.55:
                head_bonus += min(4.0, (lane1_ahead_rate - 0.50) * 20.0) * lane1_reliability
                axis_bonus += min(3.0, (lane1_ahead_rate - 0.50) * 12.0) * lane1_reliability
            if lane1_top3_rate is not None and lane1_top3_rate >= 0.55:
                axis_bonus += min(2.5, (lane1_top3_rate - 0.50) * 10.0) * lane1_reliability
            if lane1_ahead_rate is not None:
                pressure_score += max(0.0, lane1_ahead_rate - 0.50) * 18.0 * lane1_reliability

        if lane == 1 and total >= 8:
            if ahead_rate is not None and ahead_rate <= 0.48:
                toss_bonus += min(4.0, (0.52 - ahead_rate) * 14.0) * reliability
            if top3_rate is not None and top3_rate <= 0.58:
                toss_bonus += min(3.0, (0.62 - top3_rate) * 10.0) * reliability
            if ahead_rate is not None and ahead_rate >= 0.58 and top3_rate is not None and top3_rate >= 0.72:
                head_bonus += min(3.0, (ahead_rate - 0.54) * 12.0) * reliability
                axis_bonus += min(3.0, (top3_rate - 0.66) * 12.0) * reliability

        label = "相性標準"
        if total < 6:
            label = "相性データ薄"
        elif lane != 1 and lane1_meetings >= 4 and lane1_ahead_rate is not None and lane1_ahead_rate >= 0.60:
            label = "1号艇キラー"
        elif head_bonus >= 4.0 and axis_bonus >= 3.0:
            label = "相性バフ"
        elif axis_bonus >= 4.0:
            label = "相性軸バフ"
        elif toss_bonus >= 4.0:
            label = "相性デバフ"

        if lane != 1 and label in {"1号艇キラー", "相性バフ", "相性軸バフ"}:
            outer_good_count += 1
            notes.append(f"{lane}号艇{label}")

        metrics_by_lane[lane] = {
            "matchup_total_meetings": total,
            "matchup_opponents_seen": opponents_seen,
            "matchup_coverage": round(opponents_seen / 5.0, 3),
            "matchup_win_rate": round(win_rate, 5) if win_rate is not None else None,
            "matchup_top3_rate": round(top3_rate, 5) if top3_rate is not None else None,
            "matchup_ahead_rate": round(ahead_rate, 5) if ahead_rate is not None else None,
            "matchup_lane1_meetings": lane1_meetings or None,
            "matchup_lane1_win_rate": round(lane1_win_rate, 5) if lane1_win_rate is not None else None,
            "matchup_lane1_top3_rate": round(lane1_top3_rate, 5) if lane1_top3_rate is not None else None,
            "matchup_lane1_ahead_rate": round(lane1_ahead_rate, 5) if lane1_ahead_rate is not None else None,
            "matchup_head_bonus": round(clamp(head_bonus, 0.0, 8.0), 3),
            "matchup_axis_bonus": round(clamp(axis_bonus, 0.0, 8.0), 3),
            "matchup_toss_bonus": round(clamp(toss_bonus, 0.0, 8.0), 3),
            "matchup_label": label,
        }

    lane1 = metrics_by_lane.get(1, empty_matchup_metrics())
    lane1_bad = bool(
        as_int(lane1.get("matchup_total_meetings")) >= 12
        and (
            (as_float(lane1.get("matchup_ahead_rate")) is not None and as_float(lane1.get("matchup_ahead_rate")) <= 0.48)
            or (as_float(lane1.get("matchup_top3_rate")) is not None and as_float(lane1.get("matchup_top3_rate")) <= 0.58)
        )
    )
    summary = {
        "matchup_lane1_pressure_score": round(clamp(pressure_score, 0.0, 10.0), 3),
        "matchup_outer_good_count": outer_good_count,
        "matchup_lane1_bad_flag": bool_int(lane1_bad),
        "matchup_notes": "|".join(notes[:4]),
    }
    return metrics_by_lane, summary


def parse_trifecta(value: Any) -> list[int]:
    if not value:
        return []
    lanes: list[int] = []
    for part in str(value).replace(" ", "").split("-"):
        if part.isdigit():
            lane = int(part)
            if 1 <= lane <= 6:
                lanes.append(lane)
    return lanes[:3]


def class_score(value: Any) -> float:
    return {"A1": 100.0, "A2": 76.0, "B1": 43.0, "B2": 22.0}.get(str(value), 45.0)


def class_group(value: Any) -> str:
    text = str(value or "")
    return text[:1] if text else "missing"


def role_reason(label: str, condition: bool, reasons: list[str]) -> None:
    if condition:
        reasons.append(label)


def lane_head_prior(lane: int) -> float:
    return {1: 72, 2: 56, 3: 52, 4: 48, 5: 36, 6: 24}.get(lane, 40)


def lane_axis_prior(lane: int) -> float:
    return {1: 74, 2: 64, 3: 64, 4: 58, 5: 48, 6: 38}.get(lane, 50)


def lane_toss_prior(lane: int) -> float:
    return {1: 18, 2: 28, 3: 32, 4: 40, 5: 50, 6: 62}.get(lane, 40)


def result_labels(result: list[int], lane: int) -> dict[str, Any]:
    if lane in result:
        finish = result.index(lane) + 1
    else:
        finish = 4
    return {
        "actual_finish_pos": finish,
        "actual_win": bool_int(finish == 1),
        "actual_top3": bool_int(finish <= 3),
        "actual_out_top3": bool_int(finish > 3),
    }


def race_labels(row: Row) -> dict[str, Any]:
    payout = as_int(row.get("payout_yen"), 0)
    return {
        "mid_arare_flag": bool_int(5000 <= payout < 10000),
        "target_arare_flag": bool_int(payout >= 5000),
        "payout_3000_flag": bool_int(payout >= 3000),
        "payout_5000_flag": bool_int(payout >= 5000),
        "payout_10000_flag": bool_int(payout >= 10000),
        "payout_20000_flag": bool_int(payout >= 20000),
        "payout_50000_flag": bool_int(payout >= 50000),
        "non_target_flag": bool_int(0 < payout < 5000),
    }


def empty_race_labels() -> dict[str, Any]:
    return {
        "mid_arare_flag": None,
        "target_arare_flag": None,
        "payout_3000_flag": None,
        "payout_5000_flag": None,
        "payout_10000_flag": None,
        "payout_20000_flag": None,
        "payout_50000_flag": None,
        "non_target_flag": None,
    }


def empty_result_labels() -> dict[str, Any]:
    return {
        "actual_finish_pos": None,
        "actual_win": None,
        "actual_top3": None,
        "actual_out_top3": None,
    }


def race_base_score(row: Row, lane1_profile: Row | None = None) -> float:
    """Transparent chaos score proxy shared by ranking and role JSON output."""
    lane1_win = as_float(row.get("lane1_national_win_rate"))
    lane1_avg_diff = as_float(row.get("lane1_vs_avg_win_diff"))
    national_range = as_float(row.get("national_win_range"))
    wind_speed = as_float(row.get("wind_speed_m"))
    exhibition_range = as_float(row.get("exhibition_time_range"))
    profile = lane1_profile_metrics(lane1_profile)
    profile_starts = as_int(profile.get("lane1_profile_starts"))
    profile_tobi = as_float(profile.get("lane1_profile_tobi_score"))
    profile_teppan = as_float(profile.get("lane1_profile_teppan_score"))
    profile_miss_win = as_float(profile.get("lane1_profile_miss_win_rate"))
    profile_out_top3 = as_float(profile.get("lane1_profile_out_top3_rate"))
    profile_win = as_float(profile.get("lane1_profile_win_rate"))
    score = 34.0
    score += 10.0 if as_int(row.get("lane1_not_a1")) else 0.0
    score += 7.0 if as_int(row.get("lane1_b_class")) else 0.0
    score += 9.0 if lane1_win is not None and lane1_win < 5.0 else 0.0
    score += 8.0 if lane1_avg_diff is not None and lane1_avg_diff <= 0 else 0.0
    score += 9.0 if national_range is not None and national_range <= 1.5 else 0.0
    score += 5.0 if national_range is not None and 1.5 < national_range <= 2.0 else 0.0
    score += 8.0 if as_int(row.get("outer_a_count")) >= 2 else 0.0
    score += 7.0 if as_int(row.get("outer_motor_strong_flag")) else 0.0
    score += 5.0 if as_int(row.get("outer_exhibition_top_flag")) else 0.0
    score += 5.0 if as_int(row.get("early_race")) else 0.0
    score += 5.0 if wind_speed is not None and wind_speed >= 5 else 0.0
    score += 4.0 if exhibition_range is not None and exhibition_range >= 0.08 else 0.0
    if profile_starts >= 15:
        score += 7.0 if profile_tobi is not None and profile_tobi >= 0.30 else 0.0
        score += 4.0 if profile_out_top3 is not None and profile_out_top3 >= 0.34 else 0.0
        score += 3.0 if profile_miss_win is not None and profile_miss_win >= 0.72 else 0.0
        score -= 7.0 if profile_teppan is not None and profile_teppan >= 0.72 else 0.0
        score -= 3.0 if profile_win is not None and profile_win >= 0.82 else 0.0
    score -= 5.0 if as_int(row.get("fixed_entry")) else 0.0
    return round(clamp(score), 3)


def data_quality_score(row: Row) -> float:
    required = [
        "lane1_national_win_rate",
        "lane2_national_win_rate",
        "lane3_national_win_rate",
        "lane4_national_win_rate",
        "lane5_national_win_rate",
        "lane6_national_win_rate",
        "lane1_motor_quinella_rate",
        "lane2_motor_quinella_rate",
        "lane3_motor_quinella_rate",
        "lane4_motor_quinella_rate",
        "lane5_motor_quinella_rate",
        "lane6_motor_quinella_rate",
    ]
    preview = [f"lane{lane}_exhibition_time" for lane in range(1, 7)] + ["wind_speed_m", "wave_cm"]
    present = sum(1 for key in required if row.get(key) not in (None, ""))
    preview_present = sum(1 for key in preview if row.get(key) not in (None, ""))
    return round((present + 0.6 * preview_present) / (len(required) + 0.6 * len(preview)), 3)


def score_boat(row: Row, lane: int, lane1_profile: Row | None = None) -> dict[str, Any]:
    prefix = f"lane{lane}_"
    profile = lane1_profile_metrics(lane1_profile)
    profile_starts = as_int(profile.get("lane1_profile_starts"))
    profile_tobi = as_float(profile.get("lane1_profile_tobi_score"))
    profile_teppan = as_float(profile.get("lane1_profile_teppan_score"))
    profile_miss_win = as_float(profile.get("lane1_profile_miss_win_rate"))
    profile_out_top3 = as_float(profile.get("lane1_profile_out_top3_rate"))
    profile_win = as_float(profile.get("lane1_profile_win_rate"))
    cls = row.get(prefix + "class")
    national = as_float(row.get(prefix + "national_win_rate"))
    local = as_float(row.get(prefix + "local_win_rate"))
    avg_st = as_float(row.get(prefix + "avg_st"))
    motor = as_float(row.get(prefix + "motor_quinella_rate"))
    boat_rate = as_float(row.get(prefix + "boat_quinella_rate"))
    exhibition_rank = as_int(row.get(prefix + "exhibition_rank"), 0)
    exhibition_time = as_float(row.get(prefix + "exhibition_time"))
    avg_st_rank = as_int(row.get(prefix + "avg_st_rank"), 0)
    national_rank = as_int(row.get(prefix + "national_win_rank"), 0)
    tilt = as_float(row.get(prefix + "tilt"))
    lane1_win = as_float(row.get("lane1_national_win_rate"))
    national_diff_lane1 = (national - lane1_win) if national is not None and lane1_win is not None else None

    strength = (
        0.34 * scale(national, 3.0, 8.0)
        + 0.18 * scale(local, 3.0, 8.0)
        + 0.18 * scale(motor, 20.0, 55.0)
        + 0.10 * scale(boat_rate, 20.0, 55.0)
        + 0.20 * class_score(cls)
    )
    start_score = scale(avg_st, 0.08, 0.24, default=50.0, invert=True)
    exhibition_score = scale(exhibition_rank, 1, 6, default=50.0, invert=True) if exhibition_rank else 50.0
    outside_bonus = 0.0
    if lane >= 4:
        outside_bonus += 8.0 if class_group(cls) == "A" else 0.0
        outside_bonus += 8.0 if motor is not None and motor >= 40.0 else 0.0
        outside_bonus += 6.0 if exhibition_rank and exhibition_rank <= 3 else 0.0
        outside_bonus += 5.0 if avg_st_rank and avg_st_rank <= 3 else 0.0
        outside_bonus += 4.0 if tilt is not None and tilt >= 0.0 else 0.0
    center_bonus = 6.0 if lane in {2, 3, 4} else 0.0
    lane1_danger_bonus = 7.0 if lane != 1 and as_int(row.get("lane1_not_a1")) else 0.0
    lane1_danger_bonus += 6.0 if lane != 1 and (as_float(row.get("lane1_vs_avg_win_diff")) or 99) <= 0 else 0.0
    lane1_danger_bonus += 6.0 if lane != 1 and national_diff_lane1 is not None and national_diff_lane1 > 0 else 0.0
    if lane != 1 and profile_starts >= 15:
        lane1_danger_bonus += 4.0 if profile_tobi is not None and profile_tobi >= 0.30 else 0.0
        lane1_danger_bonus += 3.0 if profile_out_top3 is not None and profile_out_top3 >= 0.34 else 0.0
        lane1_danger_bonus -= 4.0 if profile_teppan is not None and profile_teppan >= 0.72 else 0.0
    range_bonus = 5.0 if (as_float(row.get("national_win_range")) or 99) <= 2.0 else 0.0

    head_morning = (
        0.42 * strength
        + 0.18 * start_score
        + 0.12 * lane_head_prior(lane)
        + center_bonus
        + outside_bonus
        + lane1_danger_bonus
        + range_bonus
    )
    head_preview = head_morning + 0.20 * exhibition_score + (4.0 if exhibition_rank and exhibition_rank <= 2 else 0.0)

    stability = (
        0.36 * strength
        + 0.18 * lane_axis_prior(lane)
        + 0.18 * start_score
        + 0.18 * exhibition_score
        + 0.10 * scale(motor, 20.0, 55.0)
    )
    axis_morning = stability - (4.0 if lane == 6 else 0.0) + (4.0 if class_group(cls) == "A" else 0.0)
    axis_preview = axis_morning + (6.0 if exhibition_rank and exhibition_rank <= 3 else 0.0)

    weakness = (
        0.28 * scale(national, 3.0, 8.0, invert=True)
        + 0.18 * scale(local, 3.0, 8.0, invert=True)
        + 0.18 * scale(motor, 20.0, 55.0, invert=True)
        + 0.12 * scale(boat_rate, 20.0, 55.0, invert=True)
        + 0.12 * scale(avg_st, 0.08, 0.24)
        + 0.12 * lane_toss_prior(lane)
    )
    weakness += 6.0 if str(cls) == "B2" else 0.0
    weakness += 4.0 if str(cls) == "B1" else 0.0
    weakness += 7.0 if exhibition_rank and exhibition_rank >= 5 else 0.0
    weakness += 6.0 if lane == 1 and as_int(row.get("lane1_not_a1")) else 0.0
    weakness += 6.0 if lane == 1 and (as_float(row.get("lane1_vs_avg_win_diff")) or 99) <= 0 else 0.0
    if lane == 1 and profile_starts >= 15:
        weakness += 7.0 if profile_tobi is not None and profile_tobi >= 0.30 else 0.0
        weakness += 4.0 if profile_out_top3 is not None and profile_out_top3 >= 0.34 else 0.0
        weakness += 3.0 if profile_miss_win is not None and profile_miss_win >= 0.72 else 0.0
        weakness -= 7.0 if profile_teppan is not None and profile_teppan >= 0.72 else 0.0
        weakness -= 3.0 if profile_win is not None and profile_win >= 0.82 else 0.0

    head_reasons: list[str] = []
    axis_reasons: list[str] = []
    toss_reasons: list[str] = []
    role_reason("A級", class_group(cls) == "A", head_reasons)
    role_reason("全国勝率上位", bool(national_rank and national_rank <= 2), head_reasons)
    role_reason("ST上位", bool(avg_st_rank and avg_st_rank <= 2), head_reasons)
    role_reason("展示上位", bool(exhibition_rank and exhibition_rank <= 2), head_reasons)
    role_reason("外枠A級/強モーター", bool(lane >= 4 and outside_bonus >= 12), head_reasons)
    role_reason("1号艇より勝率上位", bool(national_diff_lane1 is not None and national_diff_lane1 > 0), head_reasons)
    role_reason("1号艇イン履歴が不安", bool(lane != 1 and profile_starts >= 15 and profile_tobi is not None and profile_tobi >= 0.30), head_reasons)
    role_reason("イン鉄板履歴", bool(lane == 1 and profile_starts >= 15 and profile_teppan is not None and profile_teppan >= 0.72), head_reasons)

    role_reason("3着内安定候補", strength >= 58, axis_reasons)
    role_reason("モーター上位", bool(motor is not None and motor >= 40), axis_reasons)
    role_reason("展示3位以内", bool(exhibition_rank and exhibition_rank <= 3), axis_reasons)
    role_reason("ST安定", bool(avg_st_rank and avg_st_rank <= 3), axis_reasons)
    role_reason("A級", class_group(cls) == "A", axis_reasons)
    role_reason("イン鉄板履歴", bool(lane == 1 and profile_starts >= 15 and profile_teppan is not None and profile_teppan >= 0.72), axis_reasons)

    role_reason("低勝率", bool(national is not None and national < 4.5), toss_reasons)
    role_reason("B級", class_group(cls) == "B", toss_reasons)
    role_reason("モーター弱め", bool(motor is not None and motor < 30), toss_reasons)
    role_reason("展示下位", bool(exhibition_rank and exhibition_rank >= 5), toss_reasons)
    role_reason("ST不安", bool(avg_st is not None and avg_st >= 0.19), toss_reasons)
    role_reason("1号艇イン信頼度低め", bool(lane == 1 and as_int(row.get("lane1_not_a1"))), toss_reasons)
    role_reason("イン飛び履歴高め", bool(lane == 1 and profile_starts >= 15 and profile_tobi is not None and profile_tobi >= 0.30), toss_reasons)

    output = {
        "lane": lane,
        "registration_no": row.get(prefix + "registration_no"),
        "name": row.get(prefix + "name"),
        "class": cls,
        "class_group": class_group(cls),
        "national_win_rate": national,
        "local_win_rate": local,
        "avg_st": avg_st,
        "motor_quinella_rate": motor,
        "boat_quinella_rate": boat_rate,
        "exhibition_time": exhibition_time,
        "exhibition_rank": exhibition_rank or None,
        "avg_st_rank": avg_st_rank or None,
        "national_win_rank": national_rank or None,
        "strength_score": round(clamp(strength), 3),
        "start_score": round(clamp(start_score), 3),
        "exhibition_score": round(clamp(exhibition_score), 3),
        "outside_attack_score": round(clamp(outside_bonus + lane1_danger_bonus + center_bonus), 3),
        "stability_score": round(clamp(stability), 3),
        "weakness_score": round(clamp(weakness), 3),
        "head_score_morning": round(clamp(head_morning), 3),
        "head_score_preview": round(clamp(head_preview), 3),
        "axis_score_morning": round(clamp(axis_morning), 3),
        "axis_score_preview": round(clamp(axis_preview), 3),
        "toss_score_morning": round(clamp(weakness), 3),
        "toss_score_preview": round(clamp(weakness), 3),
        "head_reasons": "|".join(head_reasons[:5]) or "相対評価",
        "axis_reasons": "|".join(axis_reasons[:5]) or "相対評価",
        "toss_reasons": "|".join(toss_reasons[:5]) or "相対評価",
    }
    if lane == 1:
        output.update(profile)
    return output


def assign_roles(scored: list[Row], mode: str) -> dict[int, dict[str, Any]]:
    suffix = "_preview" if mode == "preview" else "_morning"
    # Keep lane 1 available as head/axis/opponent, but do not use it as the
    # single toss candidate. Historical checks showed lane 1 still stays top3
    # too often to treat it as a hard elimination.
    toss_pool = [item for item in scored if int(item["lane"]) != 1] or scored
    toss_sorted = sorted(toss_pool, key=lambda item: (item[f"toss_score{suffix}"], item["lane"]), reverse=True)
    toss_lane = int(toss_sorted[0]["lane"])
    head_sorted = sorted(
        [item for item in scored if item["lane"] != toss_lane],
        key=lambda item: (item[f"head_score{suffix}"], -abs(3.5 - int(item["lane"]))),
        reverse=True,
    )
    head_lanes = [int(item["lane"]) for item in head_sorted[:2]]
    axis_sorted = sorted(
        [item for item in scored if item["lane"] not in set(head_lanes + [toss_lane])],
        key=lambda item: (item[f"axis_score{suffix}"], -int(item["lane"])),
        reverse=True,
    )
    axis_lanes = [int(item["lane"]) for item in axis_sorted[:2]]
    used = set(head_lanes + axis_lanes + [toss_lane])
    opponent = next((int(item["lane"]) for item in scored if int(item["lane"]) not in used), None)
    roles: dict[int, dict[str, Any]] = {}
    for item in scored:
        lane = int(item["lane"])
        role = "opponent"
        rank = 1
        if lane in head_lanes:
            role = "head"
            rank = head_lanes.index(lane) + 1
        elif lane in axis_lanes:
            role = "axis"
            rank = axis_lanes.index(lane) + 1
        elif lane == toss_lane:
            role = "toss"
            rank = 1
        elif lane == opponent:
            role = "opponent"
            rank = 1
        roles[lane] = {f"role_{mode}": role, f"role_rank_{mode}": rank}
    return roles


def skip_recommendation(row: Row, scored: list[Row], mode: str) -> tuple[int, str]:
    suffix = "_preview" if mode == "preview" else "_morning"
    dq = data_quality_score(row)
    head_scores = sorted([float(item[f"head_score{suffix}"]) for item in scored], reverse=True)
    toss_pool = [item for item in scored if int(item["lane"]) != 1] or scored
    toss_scores = sorted([float(item[f"toss_score{suffix}"]) for item in toss_pool], reverse=True)
    reasons: list[str] = []
    if dq < 0.78:
        reasons.append("データ欠損多め")
    if head_scores[1] - head_scores[3] < 4.0:
        reasons.append("頭候補が割れ気味")
    if toss_scores[0] - toss_scores[1] < 3.0:
        reasons.append("消し候補が不明瞭")
    if mode == "preview" and not any(as_float(row.get(f"lane{lane}_exhibition_time")) is not None for lane in range(1, 7)):
        reasons.append("直前情報不足")
    return bool_int(bool(reasons)), "|".join(reasons)


def has_six_boats(race: Row) -> bool:
    return all(race.get(f"lane{lane}_registration_no") or race.get(f"lane{lane}_name") for lane in range(1, 7))


def flatten_role_rows(
    race: Row,
    lane1_profiles: dict[str, Row] | None = None,
    include_unlabeled: bool = False,
) -> list[Row]:
    valid_result = as_int(race.get("valid_for_analysis")) == 1
    trifecta = parse_trifecta(race.get("result_trifecta"))
    has_result_label = valid_result and len(trifecta) == 3
    if not include_unlabeled and not has_result_label:
        return []
    if include_unlabeled and (as_int(race.get("is_canceled")) or as_int(race.get("refund_count"))):
        return []
    if include_unlabeled and not has_six_boats(race):
        return []
    lane1_profile = lane1_profile_for_race(race, lane1_profiles or {})
    profile = lane1_profile_metrics(lane1_profile)
    scored = [score_boat(race, lane, lane1_profile=lane1_profile) for lane in range(1, 7)]
    roles_morning = assign_roles(scored, "morning")
    roles_preview = assign_roles(scored, "preview")
    labels = race_labels(race) if has_result_label else empty_race_labels()
    chaos = race_base_score(race, lane1_profile=lane1_profile)
    dq = data_quality_score(race)
    skip_morning, skip_reason_morning = skip_recommendation(race, scored, "morning")
    skip_preview, skip_reason_preview = skip_recommendation(race, scored, "preview")

    rows: list[Row] = []
    for item in scored:
        lane = int(item["lane"])
        base: Row = {
            "race_id": f"{race.get('date')}_{str(race.get('jcd')).zfill(2)}_{int(as_int(race.get('race_no'))):02d}",
            "date": race.get("date"),
            "jcd": str(race.get("jcd")).zfill(2),
            "venue_name": race.get("venue_name"),
            "grade": race.get("grade"),
            "title": race.get("title"),
            "day_label": race.get("day_label"),
            "race_no": race.get("race_no"),
            "race_name": race.get("race_name"),
            "deadline": race.get("deadline"),
            "time_zone": race.get("time_zone"),
            "early_race": race.get("early_race"),
            "fixed_entry": race.get("fixed_entry"),
            "weather": race.get("weather"),
            "wind_speed_m": race.get("wind_speed_m"),
            "wave_cm": race.get("wave_cm"),
            "result_trifecta": race.get("result_trifecta"),
            "payout_yen": race.get("payout_yen"),
            "manshu_flag": race.get("manshu_flag"),
            "big_manshu_flag": race.get("big_manshu_flag"),
            "is_labeled": bool_int(has_result_label),
            "existing_score": race.get("existing_score"),
            "national_win_range": race.get("national_win_range"),
            "lane1_vs_avg_win_diff": race.get("lane1_vs_avg_win_diff"),
            "lane1_not_a1": race.get("lane1_not_a1"),
            "lane1_b_class": race.get("lane1_b_class"),
            "a1_count": race.get("a1_count"),
            "b_class_count": race.get("b_class_count"),
            "outer_a_count": race.get("outer_a_count"),
            "outer_motor_strong_flag": race.get("outer_motor_strong_flag"),
            "outer_exhibition_top_flag": race.get("outer_exhibition_top_flag"),
            "exhibition_time_range": race.get("exhibition_time_range"),
            "chaos_score": chaos,
            "data_quality_score": dq,
            "skip_morning": skip_morning,
            "skip_reason_morning": skip_reason_morning,
            "skip_preview": skip_preview,
            "skip_reason_preview": skip_reason_preview,
        }
        base.update(profile)
        base.update(labels)
        base.update(item)
        base.update(result_labels(trifecta, lane) if has_result_label else empty_result_labels())
        base.update(roles_morning[lane])
        base.update(roles_preview[lane])
        rows.append(base)
    return rows


def write_csv(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_parquet_if_possible(rows: list[Row], path: Path) -> str:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        return f"pandas unavailable: {exc}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(path, index=False)
        return f"wrote {path}"
    except Exception as exc:  # pragma: no cover - optional dependency
        note_path = path.with_suffix(path.suffix + ".unavailable.txt")
        note_path.write_text(str(exc) + "\n", encoding="utf-8")
        return f"parquet unavailable: {exc}"


def write_dictionary(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Boat Role Dataset Dictionary",
        "",
        "このデータセットは艇別ロール候補の検証用です。舟券購入を推奨するものではありません。",
        "",
        "- `head_score_morning/preview`: 1着候補スコア。結果列は使わない。",
        "- `axis_score_morning/preview`: 3着以内候補スコア。結果列は使わない。",
        "- `toss_score_morning/preview`: 3着外候補スコア。結果列は使わない。",
        "- `role_morning/preview`: 各レース内で重複なしに割り当てた `head`, `axis`, `toss`, `opponent`。`toss` は原則2〜6号艇から選ぶ。",
        "- `actual_win`, `actual_top3`, `actual_out_top3`: 検証ラベル。",
        "- `mid_arare_flag`: 払戻5,000円以上10,000円未満。",
        "- `target_arare_flag`: 払戻5,000円以上。",
        "- `chaos_score`: レース荒れ判定用の説明可能なルールベーススコア。",
        "- `lane1_profile_*`: 1号艇選手が過去に1号艇だった時の履歴プロファイル。過去履歴から作る補助特徴量で、当日結果は使わない。",
        "- `lane1_profile_label`: `イン鉄板寄り`, `イン飛び注意`, `標準`, `データ薄め` の簡易ラベル。",
        "- `skip_morning/preview`: 見送り候補。頭候補が割れ気味、消し候補不明瞭、欠損多めなど。",
        "",
        "データリーク防止: `payout_yen`, `result_trifecta`, `actual_*` はラベル・検証専用。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    races = read_rows(Path(args.race_dataset))
    lane1_profiles = read_lane1_profiles(Path(args.lane1_profile)) if args.lane1_profile else {}
    rows: list[Row] = []
    for race in races:
        rows.extend(
            flatten_role_rows(
                race,
                lane1_profiles=lane1_profiles,
                include_unlabeled=args.include_unlabeled,
            )
        )
    write_csv(Path(args.output_csv), rows)
    parquet_note = write_parquet_if_possible(rows, Path(args.output_parquet))
    write_dictionary(Path(args.dictionary))
    race_count = len({row["race_id"] for row in rows})
    print(f"wrote {args.output_csv} rows={len(rows)} races={race_count}")
    print(f"lane1 profiles loaded={len(lane1_profiles)}")
    print(parquet_note)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--race-dataset", default="data/analysis/race_dataset.csv")
    parser.add_argument("--output-csv", default="data/analysis/boat_role_dataset.csv")
    parser.add_argument("--output-parquet", default="data/analysis/boat_role_dataset.parquet")
    parser.add_argument("--dictionary", default="data/analysis/boat_role_feature_dictionary.md")
    parser.add_argument(
        "--lane1-profile",
        default="data/analysis/lane1_racer_profiles.csv",
        help="optional historical lane-1 racer profile CSV",
    )
    parser.add_argument(
        "--include-unlabeled",
        action="store_true",
        help="include races without result/payout labels for same-day prediction display",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
