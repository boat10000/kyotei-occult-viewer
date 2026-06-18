#!/usr/bin/env python3
"""Analyze racer tendencies when assigned lane 1.

The report is historical validation only. It does not use this information to
recommend ticket purchases or guarantee future outcomes.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATASET = Path("data/analysis/boat_role_dataset.csv")
DEFAULT_CSV = Path("data/analysis/lane1_racer_profiles.csv")
DEFAULT_REPORT = Path("reports/lane1_racer_profiles.md")


USECOLS = [
    "race_id",
    "date",
    "jcd",
    "venue_name",
    "race_no",
    "grade",
    "lane",
    "registration_no",
    "name",
    "class",
    "national_win_rate",
    "local_win_rate",
    "avg_st",
    "motor_quinella_rate",
    "exhibition_rank",
    "actual_finish_pos",
    "actual_win",
    "actual_top3",
    "actual_out_top3",
    "payout_yen",
    "manshu_flag",
]


def pct(value: float | int | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{float(value) * 100:.{digits}f}%"


def yen(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{float(value):,.0f}円"


def wilson_lower(successes: float, total: float, z: float = 1.96) -> float:
    if total <= 0:
        return float("nan")
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - margin)


def wilson_upper(successes: float, total: float, z: float = 1.96) -> float:
    if total <= 0:
        return float("nan")
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return min(1.0, center + margin)


def normalize_registration(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(4) if text.isdigit() else text


def compact_name(series: pd.Series) -> str:
    cleaned = [str(v).strip() for v in series.dropna() if str(v).strip()]
    if not cleaned:
        return ""
    return pd.Series(cleaned).mode().iat[0]


def compact_class(series: pd.Series) -> str:
    cleaned = [str(v).strip() for v in series.dropna() if str(v).strip()]
    if not cleaned:
        return ""
    return cleaned[-1]


def load_lane1(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=USECOLS)
    df = df[df["actual_finish_pos"].notna()].copy()
    df["lane"] = pd.to_numeric(df["lane"], errors="coerce")
    df = df[df["lane"] == 1].copy()
    df["registration_no"] = df["registration_no"].map(normalize_registration)
    df = df[df["registration_no"] != ""].copy()
    for col in [
        "actual_win",
        "actual_top3",
        "actual_out_top3",
        "payout_yen",
        "manshu_flag",
        "national_win_rate",
        "local_win_rate",
        "avg_st",
        "motor_quinella_rate",
        "exhibition_rank",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_profiles(lane1: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    baseline = {
        "races": int(lane1["race_id"].nunique()),
        "date_min": str(lane1["date"].min()),
        "date_max": str(lane1["date"].max()),
        "racer_count": int(lane1["registration_no"].nunique()),
        "win_rate": float(lane1["actual_win"].mean()),
        "top3_rate": float(lane1["actual_top3"].mean()),
        "miss_win_rate": float((1 - lane1["actual_win"]).mean()),
        "out_top3_rate": float(lane1["actual_out_top3"].mean()),
    }

    records: list[dict[str, Any]] = []
    for registration_no, group in lane1.groupby("registration_no", dropna=False):
        starts = int(len(group))
        wins = int(group["actual_win"].sum())
        top3 = int(group["actual_top3"].sum())
        out_top3 = int(group["actual_out_top3"].sum())
        miss_win = starts - wins
        manshu_when_miss = int(group.loc[group["actual_win"] == 0, "manshu_flag"].sum())
        miss_rows = group[group["actual_win"] == 0]
        out_rows = group[group["actual_out_top3"] == 1]
        win_rate = wins / starts if starts else float("nan")
        top3_rate = top3 / starts if starts else float("nan")
        miss_win_rate = miss_win / starts if starts else float("nan")
        out_top3_rate = out_top3 / starts if starts else float("nan")
        teppan_score = 0.65 * wilson_lower(wins, starts) + 0.35 * wilson_lower(top3, starts)
        tobi_score = 0.65 * wilson_lower(miss_win, starts) + 0.35 * wilson_lower(out_top3, starts)
        records.append(
            {
                "registration_no": registration_no,
                "name": compact_name(group["name"]),
                "latest_class": compact_class(group["class"]),
                "lane1_starts": starts,
                "lane1_wins": wins,
                "lane1_top3": top3,
                "lane1_out_top3": out_top3,
                "lane1_win_rate": round(win_rate, 6),
                "lane1_miss_win_rate": round(miss_win_rate, 6),
                "lane1_top3_rate": round(top3_rate, 6),
                "lane1_out_top3_rate": round(out_top3_rate, 6),
                "win_rate_wilson_low": round(wilson_lower(wins, starts), 6),
                "top3_rate_wilson_low": round(wilson_lower(top3, starts), 6),
                "miss_win_rate_wilson_low": round(wilson_lower(miss_win, starts), 6),
                "out_top3_rate_wilson_low": round(wilson_lower(out_top3, starts), 6),
                "win_rate_wilson_high": round(wilson_upper(wins, starts), 6),
                "top3_rate_wilson_high": round(wilson_upper(top3, starts), 6),
                "teppan_score": round(teppan_score, 6),
                "tobi_score": round(tobi_score, 6),
                "manshu_when_lane1_missed": manshu_when_miss,
                "manshu_rate_when_lane1_missed": round(
                    manshu_when_miss / len(miss_rows), 6
                )
                if len(miss_rows)
                else float("nan"),
                "avg_payout_when_lane1_missed": round(float(miss_rows["payout_yen"].mean()), 1)
                if len(miss_rows)
                else float("nan"),
                "avg_payout_when_lane1_out_top3": round(float(out_rows["payout_yen"].mean()), 1)
                if len(out_rows)
                else float("nan"),
                "avg_national_win_rate": round(float(group["national_win_rate"].mean()), 3),
                "avg_local_win_rate": round(float(group["local_win_rate"].mean()), 3),
                "avg_st": round(float(group["avg_st"].mean()), 3),
                "avg_motor_quinella_rate": round(float(group["motor_quinella_rate"].mean()), 3),
                "avg_exhibition_rank": round(float(group["exhibition_rank"].mean()), 3),
                "main_venues": " / ".join(group["venue_name"].value_counts().head(3).index.astype(str)),
            }
        )

    profiles = pd.DataFrame(records)
    profiles = profiles.sort_values(
        ["lane1_starts", "teppan_score", "lane1_win_rate"],
        ascending=[False, False, False],
    )
    return profiles, baseline


def top_table(rows: pd.DataFrame, columns: list[str], max_rows: int = 15) -> str:
    if rows.empty:
        return "_該当なし_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for _, row in rows.head(max_rows).iterrows():
        values: list[str] = []
        for col in columns:
            value = row[col]
            if col.endswith("_rate") or col.endswith("_low") or col.endswith("_score"):
                values.append(pct(float(value)))
            elif col.startswith("avg_payout"):
                values.append(yen(float(value)))
            elif isinstance(value, float):
                values.append(f"{value:.3f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(profiles: pd.DataFrame, baseline: dict[str, Any], output: Path) -> None:
    eligible20 = profiles[profiles["lane1_starts"] >= 20].copy()
    eligible15 = profiles[profiles["lane1_starts"] >= 15].copy()
    teppan = eligible20.sort_values(["teppan_score", "lane1_starts"], ascending=False)
    tobi = eligible20.sort_values(["tobi_score", "lane1_starts"], ascending=False)
    out = eligible20.sort_values(
        ["out_top3_rate_wilson_low", "lane1_out_top3", "lane1_starts"], ascending=False
    )
    raw_teppan = eligible15.sort_values(["lane1_win_rate", "lane1_starts"], ascending=False)
    raw_tobi = eligible15.sort_values(["lane1_miss_win_rate", "lane1_starts"], ascending=False)

    display_cols = [
        "registration_no",
        "name",
        "latest_class",
        "lane1_starts",
        "lane1_wins",
        "lane1_win_rate",
        "lane1_top3_rate",
        "lane1_out_top3_rate",
        "teppan_score",
        "main_venues",
    ]
    tobi_cols = [
        "registration_no",
        "name",
        "latest_class",
        "lane1_starts",
        "lane1_wins",
        "lane1_miss_win_rate",
        "lane1_out_top3_rate",
        "tobi_score",
        "manshu_rate_when_lane1_missed",
        "avg_payout_when_lane1_missed",
    ]
    out_cols = [
        "registration_no",
        "name",
        "latest_class",
        "lane1_starts",
        "lane1_out_top3",
        "lane1_out_top3_rate",
        "out_top3_rate_wilson_low",
        "avg_payout_when_lane1_out_top3",
        "main_venues",
    ]

    text = f"""# 1号艇時の選手別プロファイル

このレポートは過去データの検証用です。舟券購入の推奨や利益保証ではありません。

## 対象データ

- 期間: {baseline['date_min']} 〜 {baseline['date_max']}
- 対象レース: {baseline['races']:,}R
- 1号艇経験選手: {baseline['racer_count']:,}人
- 全体の1号艇1着率: {pct(baseline['win_rate'])}
- 全体の1号艇3連対率: {pct(baseline['top3_rate'])}
- 全体の1号艇イン飛び率（1着外）: {pct(baseline['miss_win_rate'])}
- 全体の1号艇3連対外率: {pct(baseline['out_top3_rate'])}

## 定義

- イン鉄板: 1号艇時の1着率と3連対率が高い選手。小標本の上振れを抑えるため `teppan_score` は Wilson 下限を使う。
- イン飛び注意: 1号艇時に1着を逃す率、または3連対外率が高い選手。`tobi_score` も Wilson 下限を使う。
- 主表は原則 `1号艇出走20走以上`。20走未満は参考値。

## イン鉄板候補（20走以上・補正後）

{top_table(teppan, display_cols, 20)}

## イン飛び注意（20走以上・補正後）

{top_table(tobi, tobi_cols, 20)}

## 3連対外まで飛びやすい選手（20走以上・補正後）

{top_table(out, out_cols, 20)}

## 生率だけで見た参考ランキング（15走以上）

### 1着率が高い

{top_table(raw_teppan, display_cols, 15)}

### 1着外率が高い

{top_table(raw_tobi, tobi_cols, 15)}

## 使い方の注意

- 選手別の1号艇サンプルは最大でも30走台なので、単独で強い結論にしない。
- 場・相手関係・モーター・展示・風波と組み合わせて「1号艇信頼度」の補助特徴量として使うのが安全。
- 1号艇が負けることと、高配当になることは別問題。イン飛び注意でも買い目の期待値は別途検証が必要。
- 結果列は検証専用。予測時には当日の出走前に分かる選手ID・過去傾向だけを使う。
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze lane-1 racer profiles")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    lane1 = load_lane1(args.dataset)
    profiles, baseline = build_profiles(lane1)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(args.output_csv, index=False)
    write_report(profiles, baseline, args.output_report)
    print(f"wrote {args.output_csv} ({len(profiles):,} racers)")
    print(f"wrote {args.output_report}")


if __name__ == "__main__":
    main()
