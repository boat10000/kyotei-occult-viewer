#!/usr/bin/env python3
"""Attach historical lane-1 racer profiles to existing role-ranking JSON files."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


Row = dict[str, Any]


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "－"):
            return None
        output = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(output):
        return None
    return round(output, 3)


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "-", "－"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_text(value: Any) -> str | None:
    if value in (None, "", "-", "－"):
        return None
    return str(value)


def normalize_registration_no(value: Any) -> str:
    if value in (None, "", "-", "－"):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(4) if text.isdigit() else text


def profile_label(row: Row) -> str | None:
    starts = safe_int(row.get("lane1_starts")) or 0
    if starts <= 0:
        return None
    if starts < 10:
        return "データ薄め"
    tobi = safe_float(row.get("tobi_score"))
    teppan = safe_float(row.get("teppan_score"))
    miss_win = safe_float(row.get("lane1_miss_win_rate"))
    out_top3 = safe_float(row.get("lane1_out_top3_rate"))
    win = safe_float(row.get("lane1_win_rate"))
    top3 = safe_float(row.get("lane1_top3_rate"))
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


def load_profiles(path: Path) -> dict[str, Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        profiles = {
            normalize_registration_no(row.get("registration_no")): row
            for row in csv.DictReader(handle)
        }
    profiles.pop("", None)
    return profiles


def public_profile(row: Row) -> dict[str, Any]:
    return {
        "starts": safe_int(row.get("lane1_starts")),
        "win_rate": safe_float(row.get("lane1_win_rate")),
        "miss_win_rate": safe_float(row.get("lane1_miss_win_rate")),
        "top3_rate": safe_float(row.get("lane1_top3_rate")),
        "out_top3_rate": safe_float(row.get("lane1_out_top3_rate")),
        "teppan_score": safe_float(row.get("teppan_score")),
        "tobi_score": safe_float(row.get("tobi_score")),
        "manshu_rate_when_missed": safe_float(row.get("manshu_rate_when_lane1_missed")),
        "label": profile_label(row),
    }


def lane1_boat(race: Row) -> Row | None:
    for boat in race.get("boats") or []:
        if safe_int(boat.get("lane")) == 1:
            return boat
    return None


def apply_profile(data: Row, profiles: dict[str, Row]) -> int:
    applied = 0
    for race in data.get("races") or []:
        boat = lane1_boat(race)
        registration_no = normalize_registration_no(boat.get("registration_no")) if boat else ""
        raw_profile = profiles.get(registration_no)
        profile = public_profile(raw_profile) if raw_profile else None
        race.setdefault("risk_flags", {})["lane1_profile"] = profile
        if boat is not None:
            boat.setdefault("features", {})["lane1_profile"] = profile
        metrics = (
            race.setdefault("strategy", {})
            .setdefault("buy_style_1", {})
            .setdefault("metrics", {})
        )
        metrics["lane1_profile_starts"] = profile["starts"] if profile else None
        metrics["lane1_profile_tobi_score"] = profile["tobi_score"] if profile else None
        metrics["lane1_profile_teppan_score"] = profile["teppan_score"] if profile else None
        metrics["lane1_profile_label"] = profile["label"] if profile else None
        applied += 1 if profile else 0
    return applied


def run(args: argparse.Namespace) -> int:
    profiles = load_profiles(Path(args.profile))
    for raw_path in args.json_paths:
        path = Path(raw_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        applied = apply_profile(data, profiles)
        if not args.dry_run:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        print(f"{path}: lane1_profiles={applied}/{len(data.get('races') or [])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="data/analysis/lane1_racer_profiles.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("json_paths", nargs="+")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
