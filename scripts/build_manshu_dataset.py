#!/usr/bin/env python3
"""Build a one-row-per-race dataset for manshu pattern analysis."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from boatrace_official_download import normalized_from_download


FEATURE_DICTIONARY = {
    "manshu_flag": "目的変数。3連単払戻金が10,000円以上なら1。",
    "big_manshu_flag": "目的変数。3連単払戻金が50,000円以上なら1。",
    "valid_for_analysis": "中止、不成立、返還あり、払戻欠損を除いた分析対象フラグ。",
    "time_zone": "締切時刻から morning/day/evening/night/midnight に分類。",
    "early_race": "1R〜4Rなら1。",
    "semi_final": "レース名に準優を含む。",
    "final_race": "レース名に優勝を含む。",
    "selected_race": "レース名に選抜、特選、特賞、ドリーム等を含む。",
    "lane1_*": "1号艇危険度を測るための1号艇特徴量。",
    "a1_count/a2_count/b_count": "6艇の級別構成。",
    "outer_*": "4〜6号艇の実力・展示・モーターに関する特徴量。",
    "national_win_range/local_win_range": "6艇の勝率レンジ。小さいほど混戦の代理指標。",
    "exhibition_time_range": "展示タイム最大-最小。直前版特徴量。",
    "existing_score": "既存 manshu_days.html にスコアがある期間のみ結合。",
}


def normalize_date(value: str) -> tuple[str, str]:
    raw = value.strip()
    if re.fullmatch(r"\d{8}", raw):
        compact = raw
        dashed = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dashed = raw
        compact = raw.replace("-", "")
    else:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD or YYYYMMDD")
    dt.date.fromisoformat(dashed)
    return dashed, compact


def date_range(start: str, end: str) -> list[tuple[str, str]]:
    start_dash, _start_compact = normalize_date(start)
    end_dash, _end_compact = normalize_date(end)
    current = dt.date.fromisoformat(start_dash)
    last = dt.date.fromisoformat(end_dash)
    if current > last:
        raise argparse.ArgumentTypeError("start date must be on or before end date")
    dates: list[tuple[str, str]] = []
    while current <= last:
        dashed = current.isoformat()
        dates.append((dashed, dashed.replace("-", "")))
        current += dt.timedelta(days=1)
    return dates


def num(value: Any) -> float | None:
    if value in (None, "", "-", "－"):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def intish(value: Any) -> int | None:
    if value in (None, "", "-", "－"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bool_int(value: bool) -> int:
    return 1 if value else 0


def bucket(value: float | None, cuts: list[float], labels: list[str]) -> str:
    if value is None:
        return "missing"
    for cut, label in zip(cuts, labels):
        if value < cut:
            return label
    return labels[-1]


def time_zone(deadline: str | None) -> str:
    if not deadline or ":" not in deadline:
        return "missing"
    match = re.search(r"(\d{1,2}):(\d{2})", str(deadline))
    if not match:
        return "missing"
    hour, minute = int(match.group(1)), int(match.group(2))
    minutes = hour * 60 + minute
    if minutes < 12 * 60:
        return "morning"
    if minutes < 16 * 60:
        return "day"
    if minutes < 18 * 60 + 30:
        return "evening"
    if minutes < 20 * 60 + 30:
        return "night"
    return "midnight"


def rank_values(items: list[tuple[int, float | None]], lower_is_better: bool = False) -> dict[int, int | None]:
    values = [(lane, value) for lane, value in items if value is not None]
    values.sort(key=lambda item: item[1], reverse=not lower_is_better)
    ranks: dict[int, int | None] = {lane: None for lane, _value in items}
    previous_value: float | None = None
    previous_rank = 0
    for index, (lane, value) in enumerate(values, start=1):
        rank = previous_rank if previous_value == value else index
        ranks[lane] = rank
        previous_value = value
        previous_rank = rank
    return ranks


def load_existing_scores(path: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"const DATA = (\{.*?\});\s*const DATES", text, re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    scores: dict[tuple[str, str, int], dict[str, Any]] = {}
    for date, rows in payload.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("v") and row.get("r"):
                scores[(date, str(row["v"]).zfill(2), int(row["r"]))] = row
    return scores


def load_normalized(date_dash: str, date_compact: str, args: argparse.Namespace) -> dict[str, Any] | None:
    path = Path(args.normalized_dir) / f"{date_compact}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    raw_dir = Path(args.raw_dir) / date_compact
    normalized = normalized_from_download(raw_dir, date_dash)
    if normalized and args.write_missing_normalized:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def boat_value(boat: dict[str, Any], path: list[str]) -> Any:
    current: Any = boat
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def class_group(value: str | None) -> str:
    if not value:
        return "missing"
    return value[:1]


def flatten_race(date: str, venue: dict[str, Any], race: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    boats = {boat.get("lane"): boat for boat in race.get("boats", []) if boat.get("lane")}
    boat_list = [boats.get(lane, {"lane": lane, "preview": {}}) for lane in range(1, 7)]
    race_no = intish(race.get("race_no")) or 0
    result = race.get("result") or {}
    weather = race.get("weather") or {}
    conditions = race.get("conditions") or {}
    payout = intish(result.get("payout_yen"))
    refunds = result.get("refunds") or []
    canceled = bool(result.get("is_canceled"))
    valid = payout is not None and not canceled and len(refunds) == 0

    national_wins = [(lane, num(boat_value(boats.get(lane, {}), ["national", "win_rate"]))) for lane in range(1, 7)]
    local_wins = [(lane, num(boat_value(boats.get(lane, {}), ["local", "win_rate"]))) for lane in range(1, 7)]
    avg_sts = [(lane, num(boat_value(boats.get(lane, {}), ["avg_st"]))) for lane in range(1, 7)]
    motor_rates = [(lane, num(boat_value(boats.get(lane, {}), ["motor", "quinella_rate"]))) for lane in range(1, 7)]
    exhibition = [(lane, num(boat_value(boats.get(lane, {}), ["preview", "exhibition_time"]))) for lane in range(1, 7)]
    exhibition_rank = rank_values(exhibition, lower_is_better=True)
    national_rank = rank_values(national_wins, lower_is_better=False)
    avg_st_rank = rank_values(avg_sts, lower_is_better=True)

    def values(items: list[tuple[int, float | None]]) -> list[float]:
        return [value for _lane, value in items if value is not None]

    def range_or_none(items: list[tuple[int, float | None]]) -> float | None:
        vals = values(items)
        return round(max(vals) - min(vals), 4) if vals else None

    classes = [boat.get("class") for boat in boat_list]
    outer_boats = [boats.get(lane, {}) for lane in range(4, 7)]
    lane1 = boats.get(1, {})
    lane2 = boats.get(2, {})
    lane1_win = num(boat_value(lane1, ["national", "win_rate"]))
    lane2_win = num(boat_value(lane2, ["national", "win_rate"]))
    avg_win_values = values(national_wins)
    outer_win_values = [num(boat_value(boat, ["national", "win_rate"])) for boat in outer_boats]
    outer_win_values = [value for value in outer_win_values if value is not None]

    row: dict[str, Any] = {
        "date": date,
        "jcd": venue.get("jcd"),
        "venue_name": venue.get("name"),
        "grade": venue.get("grade"),
        "title": venue.get("title"),
        "day_label": venue.get("day_label"),
        "race_no": race_no,
        "race_name": race.get("race_name"),
        "deadline": race.get("deadline"),
        "time_zone": time_zone(race.get("deadline")),
        "morning_flag": bool_int(time_zone(race.get("deadline")) == "morning"),
        "night_flag": bool_int(time_zone(race.get("deadline")) in {"night", "midnight"}),
        "midnight_flag": bool_int(time_zone(race.get("deadline")) == "midnight"),
        "early_race": bool_int(race_no <= 4),
        "semi_final": bool_int("準優" in str(race.get("race_name") or "")),
        "final_race": bool_int("優勝" in str(race.get("race_name") or "")),
        "selected_race": bool_int(any(word in str(race.get("race_name") or "") for word in ["選抜", "特選", "特賞", "ドリーム"])),
        "fixed_entry": bool_int(bool(conditions.get("fixed_entry"))),
        "stabilizer": bool_int(bool(conditions.get("stabilizer"))),
        "weather": weather.get("weather"),
        "wind_direction": weather.get("wind_direction"),
        "wind_speed_m": num(weather.get("wind_speed_m")),
        "wind_speed_bucket": bucket(num(weather.get("wind_speed_m")), [2, 4, 6], ["0-1m", "2-3m", "4-5m", "6m+"]),
        "wave_cm": num(weather.get("wave_cm")),
        "wave_bucket": bucket(num(weather.get("wave_cm")), [2, 5, 8], ["0-1cm", "2-4cm", "5-7cm", "8cm+"]),
        "result_trifecta": result.get("trifecta"),
        "payout_yen": payout,
        "popularity": intish(result.get("popularity")),
        "is_canceled": bool_int(canceled),
        "refund_count": len(refunds),
        "decision": result.get("decision"),
        "manshu_flag": bool_int(bool(valid and payout is not None and payout >= 10000)),
        "big_manshu_flag": bool_int(bool(valid and payout is not None and payout >= 50000)),
        "valid_for_analysis": bool_int(valid),
        "existing_score": existing.get("s") if existing else None,
        "existing_reason": existing.get("k") if existing else None,
        "existing_manshu_flag": existing.get("m") if existing else None,
    }

    for boat in boat_list:
        lane = boat.get("lane")
        prefix = f"lane{lane}"
        row.update(
            {
                f"{prefix}_registration_no": boat.get("registration_no"),
                f"{prefix}_name": boat.get("name"),
                f"{prefix}_class": boat.get("class"),
                f"{prefix}_class_group": class_group(boat.get("class")),
                f"{prefix}_branch": boat.get("branch"),
                f"{prefix}_age": intish(boat.get("age")),
                f"{prefix}_weight_kg": num(boat.get("weight_kg")),
                f"{prefix}_f_count": intish(boat.get("f_count")),
                f"{prefix}_l_count": intish(boat.get("l_count")),
                f"{prefix}_avg_st": num(boat.get("avg_st")),
                f"{prefix}_national_win_rate": num(boat_value(boat, ["national", "win_rate"])),
                f"{prefix}_national_quinella_rate": num(boat_value(boat, ["national", "quinella_rate"])),
                f"{prefix}_national_trio_rate": num(boat_value(boat, ["national", "trio_rate"])),
                f"{prefix}_local_win_rate": num(boat_value(boat, ["local", "win_rate"])),
                f"{prefix}_local_quinella_rate": num(boat_value(boat, ["local", "quinella_rate"])),
                f"{prefix}_local_trio_rate": num(boat_value(boat, ["local", "trio_rate"])),
                f"{prefix}_motor_no": boat_value(boat, ["motor", "no"]),
                f"{prefix}_motor_quinella_rate": num(boat_value(boat, ["motor", "quinella_rate"])),
                f"{prefix}_motor_trio_rate": num(boat_value(boat, ["motor", "trio_rate"])),
                f"{prefix}_boat_no": boat_value(boat, ["boat", "no"]),
                f"{prefix}_boat_quinella_rate": num(boat_value(boat, ["boat", "quinella_rate"])),
                f"{prefix}_boat_trio_rate": num(boat_value(boat, ["boat", "trio_rate"])),
                f"{prefix}_exhibition_time": num(boat_value(boat, ["preview", "exhibition_time"])),
                f"{prefix}_exhibition_rank": exhibition_rank.get(lane),
                f"{prefix}_exhibition_entry": intish(boat_value(boat, ["preview", "exhibition_entry"])),
                f"{prefix}_exhibition_st": num(boat_value(boat, ["preview", "exhibition_st"])),
                f"{prefix}_tilt": num(boat_value(boat, ["preview", "tilt"])),
                f"{prefix}_national_win_rank": national_rank.get(lane),
                f"{prefix}_avg_st_rank": avg_st_rank.get(lane),
            }
        )

    row.update(
        {
            "lane1_b_class": bool_int(str(row.get("lane1_class") or "").startswith("B")),
            "lane1_not_a1": bool_int(row.get("lane1_class") != "A1"),
            "lane1_a2_or_lower": bool_int(row.get("lane1_class") != "A1"),
            "lane1_national_win_bucket": bucket(lane1_win, [4.5, 5.5, 6.5], ["lt4.5", "4.5-5.49", "5.5-6.49", "6.5+"]),
            "lane1_local_win_bucket": bucket(num(boat_value(lane1, ["local", "win_rate"])), [4.5, 5.5, 6.5], ["lt4.5", "4.5-5.49", "5.5-6.49", "6.5+"]),
            "lane1_exhibition_rank4plus": bool_int((exhibition_rank.get(1) or 99) >= 4),
            "lane1_vs_lane2_win_diff": round(lane1_win - lane2_win, 4) if lane1_win is not None and lane2_win is not None else None,
            "lane1_vs_avg_win_diff": round(lane1_win - (sum(avg_win_values) / len(avg_win_values)), 4) if lane1_win is not None and avg_win_values else None,
            "lane1_vs_best_outer_win_diff": round(lane1_win - max(outer_win_values), 4) if lane1_win is not None and outer_win_values else None,
            "a1_count": sum(1 for value in classes if value == "A1"),
            "a2_count": sum(1 for value in classes if value == "A2"),
            "b1_count": sum(1 for value in classes if value == "B1"),
            "b2_count": sum(1 for value in classes if value == "B2"),
            "b_count": sum(1 for value in classes if str(value or "").startswith("B")),
            "outer_a_count": sum(1 for boat in outer_boats if str(boat.get("class") or "").startswith("A")),
            "outer_a1_count": sum(1 for boat in outer_boats if boat.get("class") == "A1"),
            "outer_a2plus_count": sum(1 for boat in outer_boats if boat.get("class") in {"A1", "A2"}),
            "national_win_range": range_or_none(national_wins),
            "local_win_range": range_or_none(local_wins),
            "avg_st_range": range_or_none(avg_sts),
            "motor_quinella_range": range_or_none(motor_rates),
            "exhibition_time_range": range_or_none(exhibition),
            "top2_national_win_gap": None,
            "top3_national_win_gap": None,
            "outer_motor_strong_flag": bool_int(any((num(boat_value(boat, ["motor", "quinella_rate"])) or 0) >= 40 for boat in outer_boats)),
            "outer_exhibition_top_flag": bool_int(any((exhibition_rank.get(lane) or 99) <= 2 for lane in range(4, 7))),
            "outer_tilt_high_flag": bool_int(any((num(boat_value(boat, ["preview", "tilt"])) or 0) >= 0.5 for boat in outer_boats)),
            "outer_exhibition_beats_lane1": bool_int(any((exhibition_rank.get(lane) or 99) < (exhibition_rank.get(1) or 99) for lane in range(4, 7))),
            "outer_avgst_beats_lane1": bool_int(any((avg_st_rank.get(lane) or 99) < (avg_st_rank.get(1) or 99) for lane in range(4, 7))),
        }
    )

    sorted_wins = sorted(values(national_wins), reverse=True)
    if len(sorted_wins) >= 2:
        row["top2_national_win_gap"] = round(sorted_wins[0] - sorted_wins[1], 4)
    if len(sorted_wins) >= 3:
        row["top3_national_win_gap"] = round(sorted_wins[0] - sorted_wins[2], 4)
    return row


def build_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dates = [(normalize_date(args.date)[0], normalize_date(args.date)[1])] if args.date else date_range(args.start_date, args.end_date)
    existing_scores = load_existing_scores(Path(args.existing_days_html))
    rows: list[dict[str, Any]] = []
    quality = {
        "dates_requested": len(dates),
        "dates_loaded": 0,
        "normalized_missing": [],
        "races_total": 0,
        "races_valid": 0,
        "races_with_six_boats": 0,
        "existing_score_matched": 0,
    }
    for date_dash, date_compact in dates:
        normalized = load_normalized(date_dash, date_compact, args)
        if not normalized:
            quality["normalized_missing"].append(date_dash)
            continue
        quality["dates_loaded"] += 1
        for venue in normalized.get("venues", []):
            jcd = str(venue.get("jcd") or "").zfill(2)
            for race in venue.get("races", []):
                race_no = intish(race.get("race_no")) or 0
                existing = existing_scores.get((date_dash, jcd, race_no))
                row = flatten_race(date_dash, venue, race, existing)
                rows.append(row)
                quality["races_total"] += 1
                quality["races_valid"] += row["valid_for_analysis"]
                quality["races_with_six_boats"] += bool_int(len(race.get("boats", [])) == 6)
                quality["existing_score_matched"] += bool_int(existing is not None)
    return rows, quality


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_parquet_if_possible(rows: list[dict[str, Any]], path: Path) -> str:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:
        note = f"pandas unavailable: {exc}"
        path.with_suffix(path.suffix + ".unavailable.txt").write_text(note + "\n", encoding="utf-8")
        return note
    try:
        pd.DataFrame(rows).to_parquet(path, index=False)
        return f"wrote {path}"
    except Exception as exc:
        note = f"parquet unavailable: {exc}"
        path.with_suffix(path.suffix + ".unavailable.txt").write_text(note + "\n", encoding="utf-8")
        return note


def write_feature_dictionary(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Feature Dictionary", "", "予測に使う場合は、結果後にしか分からない列を除外する。", ""]
    for key, description in FEATURE_DICTIONARY.items():
        lines.append(f"- `{key}`: {description}")
    lines.extend(
        [
            "",
            "## データリーク注意",
            "",
            "- 朝版で使える: 出走表、開催、番組、選手、モーター/ボートの事前情報。",
            "- 直前版で使える: 展示タイム、展示進入、展示ST、気象、オッズ。",
            "- 予測に使わない: `payout_yen`, `manshu_flag`, `result_trifecta`, `popularity`, `decision`, 実際の着順。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_quality_report(path: Path, rows: list[dict[str, Any]], quality: dict[str, Any], parquet_note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    valid_rows = [row for row in rows if row.get("valid_for_analysis")]
    manshu = sum(int(row.get("manshu_flag") or 0) for row in valid_rows)
    missing_counts: dict[str, int] = {}
    key_fields = [
        "lane1_class",
        "lane1_national_win_rate",
        "lane1_local_win_rate",
        "lane1_motor_quinella_rate",
        "lane1_exhibition_time",
        "wind_speed_m",
        "wave_cm",
        "grade",
        "existing_score",
    ]
    for key in key_fields:
        missing_counts[key] = sum(1 for row in rows if row.get(key) in (None, ""))
    lines = [
        "# Manshu Data Quality Report",
        "",
        "このレポートは分析用データセット生成時点の品質確認であり、舟券購入を推奨するものではありません。",
        "",
        f"- 取得日数: {quality['dates_loaded']} / {quality['dates_requested']}",
        f"- レース数: {quality['races_total']}",
        f"- 分析対象レース数: {quality['races_valid']}",
        f"- 6艇情報あり: {quality['races_with_six_boats']}",
        f"- 万舟数: {manshu}",
        f"- 全体万舟率: {(manshu / len(valid_rows) * 100 if valid_rows else 0):.2f}%",
        f"- 既存スコア結合数: {quality['existing_score_matched']}",
        f"- Parquet出力: {parquet_note}",
        "",
        "## 欠損数",
        "",
    ]
    for key, count in missing_counts.items():
        rate = count / len(rows) * 100 if rows else 0
        lines.append(f"- `{key}`: {count} ({rate:.1f}%)")
    if quality["normalized_missing"]:
        lines.extend(["", "## 正規化データなし", ""])
        lines.extend(f"- {date}" for date in quality["normalized_missing"])
    lines.extend(
        [
            "",
            "## 注意",
            "",
            "- 公式DLのBファイルには3連率、F/L数、平均STが含まれない場合がある。",
            "- グレード、開催タイトル、日次はOpenAPI v3 programsがある場合のみ非公式補助で補完される。",
            "- 展示タイム・展示STは直前版特徴量として扱う。",
            "- `popularity`, `decision`, `result_trifecta`, `payout_yen` はラベル・検証専用。",
            "- `existing_score` は `manshu_days.html` と期間が重なる場合のみ結合される。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    if not args.date and not (args.start_date and args.end_date):
        raise SystemExit("provide --date or both --start-date and --end-date")
    rows, quality = build_rows(args)
    if not rows:
        print("no rows built", file=sys.stderr)
        return 1
    csv_path = Path(args.output_csv)
    write_csv(rows, csv_path)
    parquet_note = write_parquet_if_possible(rows, Path(args.output_parquet))
    write_feature_dictionary(Path(args.feature_dictionary))
    write_quality_report(Path(args.quality_report), rows, quality, parquet_note)
    print(f"wrote {csv_path} rows={len(rows)} valid={quality['races_valid']}")
    print(parquet_note)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="JST date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--start-date", help="JST start date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", help="JST end date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--normalized-dir", default="data/normalized")
    parser.add_argument("--write-missing-normalized", action="store_true")
    parser.add_argument("--existing-days-html", default="manshu_days.html")
    parser.add_argument("--output-csv", default="data/analysis/race_dataset.csv")
    parser.add_argument("--output-parquet", default="data/analysis/race_dataset.parquet")
    parser.add_argument("--feature-dictionary", default="data/analysis/feature_dictionary.md")
    parser.add_argument("--quality-report", default="reports/data_quality_report.md")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
