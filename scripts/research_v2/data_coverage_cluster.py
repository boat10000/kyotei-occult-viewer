#!/usr/bin/env python3
"""Data coverage and manshu pattern clustering for research_v2."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))

RESULT_OR_LEAKAGE_COLUMNS = {
    "result_trifecta",
    "payout_yen",
    "popularity",
    "decision",
    "manshu_flag",
    "big_manshu_flag",
    "valid_for_analysis",
    "existing_manshu_flag",
}

CLUSTER_FEATURES = [
    "race_no",
    "early_race",
    "morning_flag",
    "night_flag",
    "fixed_entry",
    "stabilizer",
    "wind_speed_m",
    "wave_cm",
    "lane1_not_a1",
    "lane1_b_class",
    "lane1_national_win_rate",
    "lane1_local_win_rate",
    "lane1_motor_quinella_rate",
    "lane1_boat_quinella_rate",
    "lane1_exhibition_time",
    "lane1_exhibition_rank",
    "lane1_exhibition_st",
    "lane1_avg_st_rank",
    "lane1_vs_avg_win_diff",
    "lane1_vs_lane2_win_diff",
    "lane1_vs_best_outer_win_diff",
    "a1_count",
    "a2_count",
    "b_count",
    "outer_a_count",
    "outer_a1_count",
    "outer_motor_strong_flag",
    "outer_exhibition_top_flag",
    "outer_tilt_high_flag",
    "outer_exhibition_beats_lane1",
    "outer_avgst_beats_lane1",
    "national_win_range",
    "local_win_range",
    "avg_st_range",
    "motor_quinella_range",
    "exhibition_time_range",
    "top2_national_win_gap",
    "top3_national_win_gap",
]

COVERAGE_ITEMS = {
    "展示タイム": [f"lane{lane}_exhibition_time" for lane in range(1, 7)],
    "展示ST": [f"lane{lane}_exhibition_st" for lane in range(1, 7)],
    "1周タイム": [f"lane{lane}_lap_time" for lane in range(1, 7)],
    "まわり足": [f"lane{lane}_turn_time" for lane in range(1, 7)],
    "直線タイム": [f"lane{lane}_straight_time" for lane in range(1, 7)],
    "チルト": [f"lane{lane}_tilt" for lane in range(1, 7)],
    "展示進入": [f"lane{lane}_exhibition_entry" for lane in range(1, 7)],
    "本番進入": [f"lane{lane}_actual_entry" for lane in range(1, 7)],
    "風向": ["wind_direction"],
    "風速": ["wind_speed_m"],
    "波高": ["wave_cm"],
    "気温": ["air_temp_c"],
    "水温": ["water_temp_c"],
    "天候": ["weather"],
    "潮位": ["tide_level"],
    "潮回り": ["tide_name"],
    "満潮/干潮": ["high_tide_time", "low_tide_time"],
    "モーター2連率": [f"lane{lane}_motor_quinella_rate" for lane in range(1, 7)],
    "モーター3連率": [f"lane{lane}_motor_trio_rate" for lane in range(1, 7)],
    "ボート2連率": [f"lane{lane}_boat_quinella_rate" for lane in range(1, 7)],
    "ボート3連率": [f"lane{lane}_boat_trio_rate" for lane in range(1, 7)],
    "フライング/出遅れ": [f"lane{lane}_f_count" for lane in range(1, 7)] + [f"lane{lane}_l_count" for lane in range(1, 7)],
    "欠場・返還": ["refund_count", "is_canceled"],
    "オッズ時刻別": ["odds_snapshot_time"],
}


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "-", "nan") or pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def pct(num: float, den: float) -> float | None:
    return round(num / den * 100, 2) if den else None


def season(month: int) -> str:
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "autumn"


def parse_winner(value: Any) -> int | None:
    if not value:
        return None
    for part in str(value).replace(" ", "").split("-"):
        if part.isdigit():
            return int(part)
    digits = [int(ch) for ch in str(value) if ch.isdigit()]
    return digits[0] if digits else None


def is_joshi(row: pd.Series) -> bool:
    text = " ".join(str(row.get(col) or "") for col in ["title", "race_name"])
    return any(word in text for word in ["女子", "レディース", "ヴィーナス", "ビーナス", "なでしこ"])


def coverage_rate(df: pd.DataFrame, cols: list[str]) -> tuple[int, int, float | None, str]:
    existing = [col for col in cols if col in df.columns]
    if not existing:
        return 0, len(df), 0.0, "not_collected"
    complete = df[existing].notna().all(axis=1).sum()
    return int(complete), len(df), pct(float(complete), len(df)), "partial" if len(existing) < len(cols) else "collected"


def write_coverage_report(df: pd.DataFrame, path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item, cols in COVERAGE_ITEMS.items():
        complete, total, rate, status = coverage_rate(df, cols)
        rows.append({"item": item, "complete_rows": complete, "total_rows": total, "coverage_pct": rate, "status": status})
    by_month = df.assign(month=df["date"].astype(str).str[:7]).groupby("month").size().to_dict()
    by_venue = df.groupby("venue_name").size().sort_values(ascending=False).head(20).to_dict()
    estimated_bytes_per_day = int(max(1, len(df.to_csv(index=False).encode("utf-8")) / max(1, df["date"].nunique())))
    lines = [
        "# research_v2 Data Coverage Report",
        "",
        "既存の正規化済み分析データを読み、追加収集候補ごとの取得率を確認しました。",
        "",
        f"- 生成時刻: {now_iso()}",
        f"- 対象期間: {df['date'].min()} - {df['date'].max()}",
        f"- レース行数: {len(df):,}",
        f"- 会場数: {df['venue_name'].nunique()}",
        "",
        "## 項目別取得率",
        "",
        "| 項目 | 状態 | 完全行 | 取得率 |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in rows:
        lines.append(f"| {row['item']} | {row['status']} | {row['complete_rows']}/{row['total_rows']} | {row['coverage_pct']} |")
    lines.extend(
        [
            "",
            "## 期間別レース数",
            "",
            *[f"- {month}: {count:,}" for month, count in by_month.items()],
            "",
            "## 会場別レース数 TOP20",
            "",
            *[f"- {venue}: {count:,}" for venue, count in by_venue.items()],
            "",
            "## GitHub容量対策の見積もり",
            "",
            f"- 現在の分析CSV相当: 約 {estimated_bytes_per_day:,} bytes/day",
            "- 生HTMLや巨大DBはGit管理しない。必要な場合はローカルキャッシュまたはActions artifactへ置く。",
            "- Git管理するのは小さな正規化サマリ、検証結果、モデルメタデータに限定する。",
            "- 新しい定期workflowは追加しない。追加する場合も最初は `workflow_dispatch` の手動実行のみ。",
            "",
            "## 欠損方針",
            "",
            "- 取得できない項目を推測で埋めない。",
            "- 欠損理由、取得元、取得時刻、利用可能時刻、schema_versionを追加収集データに持たせる。",
            "- 過去再取得時は理由なく上書きせず、追記型または冪等な更新にする。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    cols = [col for col in CLUSTER_FEATURES if col in df.columns and col not in RESULT_OR_LEAKAGE_COLUMNS]
    x = df[cols].copy()
    for col in cols:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.fillna(x.median(numeric_only=True)).fillna(0.0)
    return x, cols


def compare_cluster_methods(x_manshu: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    max_k = min(7, max(3, len(x_manshu) // 80))
    for k in range(3, max_k + 1):
        if len(x_manshu) <= k:
            continue
        km = KMeans(n_clusters=k, random_state=20260625, n_init=20)
        labels = km.fit_predict(x_manshu)
        rows.append({"method": "KMeans", "clusters": k, "silhouette": round(float(silhouette_score(x_manshu, labels)), 6), "assignable_new_races": True})
        gm = GaussianMixture(n_components=k, random_state=20260625)
        g_labels = gm.fit_predict(x_manshu)
        rows.append({"method": "GaussianMixture", "clusters": k, "silhouette": round(float(silhouette_score(x_manshu, g_labels)), 6), "assignable_new_races": True})
        if len(x_manshu) <= 4000:
            ag = AgglomerativeClustering(n_clusters=k)
            a_labels = ag.fit_predict(x_manshu)
            rows.append({"method": "Agglomerative", "clusters": k, "silhouette": round(float(silhouette_score(x_manshu, a_labels)), 6), "assignable_new_races": False})
    return rows


def cluster_name(row: dict[str, Any]) -> str:
    features = row.get("main_features", "")
    if "lane1_not_a1" in features or "lane1_b_class" in features:
        return "1号艇弱化型"
    if "outer_exhibition" in features or "outer_a_count" in features:
        return "外枠上振れ型"
    if "wind_speed" in features or "wave_cm" in features:
        return "水面荒れ型"
    if "early_race" in features:
        return "前半荒れ型"
    return "混戦型"


def fit_cluster_model(df: pd.DataFrame, model_path: Path, profiles_path: Path, validation_path: Path, assignment_path: Path) -> None:
    valid = df[df["valid_for_analysis"].astype(int) == 1].copy()
    valid["winner_lane"] = valid["result_trifecta"].map(parse_winner)
    valid["lane1_fly"] = valid["winner_lane"].ne(1)
    valid["month"] = valid["date"].astype(str).str[:7]
    valid["season"] = pd.to_datetime(valid["date"]).dt.month.map(season)
    valid["is_joshi"] = valid.apply(is_joshi, axis=1)
    train = valid[valid["date"].astype(str) <= "2026-04-30"].copy()
    x, cols = prepare_features(valid)
    train_x = x.loc[train.index]
    manshu_train_idx = train[train["manshu_flag"].astype(int) == 1].index
    scaler = StandardScaler()
    scaled_train_manshu = scaler.fit_transform(train_x.loc[manshu_train_idx])
    method_rows = compare_cluster_methods(scaled_train_manshu)
    candidates = [row for row in method_rows if row["method"] == "KMeans"]
    best = max(candidates, key=lambda row: (row["silhouette"], -row["clusters"])) if candidates else {"clusters": 5, "silhouette": None}
    model = KMeans(n_clusters=int(best["clusters"]), random_state=20260625, n_init=30)
    model.fit(scaled_train_manshu)
    all_scaled = scaler.transform(x)
    distances = model.transform(all_scaled)
    nearest = distances.argmin(axis=1)
    nearest_distance = distances.min(axis=1)
    train_distances = model.transform(scaled_train_manshu).min(axis=1)
    threshold = float(np.quantile(train_distances, 0.95))
    valid["cluster_id"] = [f"C{int(label)}" if dist <= threshold else "unknown" for label, dist in zip(nearest, nearest_distance)]
    valid["cluster_similarity"] = [round(max(0.0, 1.0 - dist / threshold), 4) if threshold else 0.0 for dist in nearest_distance]
    baseline_rate = valid["manshu_flag"].mean()
    profiles: list[dict[str, Any]] = []
    global_means = x.mean()
    for cluster_id, group in valid.groupby("cluster_id"):
        if cluster_id == "unknown":
            centroid = x.loc[group.index].mean()
        else:
            center = scaler.inverse_transform(model.cluster_centers_[int(cluster_id[1:])].reshape(1, -1))[0]
            centroid = pd.Series(center, index=cols)
        diffs = (centroid - global_means).abs().sort_values(ascending=False)
        main = ",".join(diffs.head(6).index.tolist())
        payouts = pd.to_numeric(group["payout_yen"], errors="coerce").dropna()
        manshu_count = int(group["manshu_flag"].astype(int).sum())
        head_counts = Counter(group["winner_lane"].dropna().astype(int).tolist())
        venue_counts = group["venue_name"].value_counts().head(5).to_dict()
        season_counts = group["season"].value_counts().to_dict()
        month_rates = group.groupby("month")["manshu_flag"].mean()
        row = {
            "cluster_id": cluster_id,
            "name": "",
            "race_count": int(len(group)),
            "manshu_count": manshu_count,
            "manshu_rate_pct": pct(manshu_count, len(group)),
            "baseline_lift": round((manshu_count / len(group)) / baseline_rate, 4) if baseline_rate else None,
            "avg_payout_yen": round(float(payouts.mean()), 2) if len(payouts) else None,
            "median_payout_yen": round(float(payouts.median()), 2) if len(payouts) else None,
            "lane1_fly_rate_pct": pct(float(group["lane1_fly"].mean()), 1),
            "head_lane_distribution": json.dumps(dict(head_counts), ensure_ascii=False),
            "main_features": main,
            "venue_distribution_top5": json.dumps(venue_counts, ensure_ascii=False),
            "season_distribution": json.dumps(season_counts, ensure_ascii=False),
            "joshi_rate_pct": pct(float(group["is_joshi"].mean()), 1),
            "time_stability_std": round(float(month_rates.std()), 6) if len(month_rates) > 1 else None,
            "similarity_threshold": round(threshold, 6),
            "sample_warning": "sample_small" if len(group) < 100 else "",
        }
        row["name"] = cluster_name(row)
        profiles.append(row)
    profiles.sort(key=lambda row: (row["cluster_id"] == "unknown", -(row["manshu_rate_pct"] or 0)))
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    with profiles_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(profiles[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(profiles)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as handle:
        pickle.dump({"version": "research-v2-manshu-cluster-1", "scaler": scaler, "model": model, "features": cols, "threshold": threshold, "method_comparison": method_rows}, handle)

    latest_date = str(valid["date"].max())
    day = valid[valid["date"].astype(str) == latest_date]
    assignments = [
        {
            "race_id": f"{row.date}_{str(row.jcd).zfill(2)}_{int(row.race_no):02d}",
            "date": row.date,
            "venue_name": row.venue_name,
            "race_no": int(row.race_no),
            "cluster_id": row.cluster_id,
            "cluster_similarity": row.cluster_similarity,
            "unknown": row.cluster_id == "unknown",
        }
        for row in day.itertuples()
    ]
    assignment_path.parent.mkdir(parents=True, exist_ok=True)
    assignment_path.write_text(
        json.dumps(
            {"version": "research-v2-cluster-assignment-1", "date": latest_date, "generated_at": now_iso(), "assignments": assignments},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    validation_lines = [
        "# research_v2 Manshu Cluster Validation",
        "",
        "万舟レースで代表パターンを作り、全レースを分母として各クラスタの万舟率とリフトを計算しました。",
        "",
        "## 手法比較",
        "",
        "| 手法 | クラスタ数 | silhouette | 新規割当 |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in method_rows:
        validation_lines.append(f"| {row['method']} | {row['clusters']} | {row['silhouette']} | {row['assignable_new_races']} |")
    validation_lines.extend(
        [
            "",
            "## 採用",
            "",
            f"- 採用手法: KMeans k={best['clusters']}",
            f"- 類似度閾値: {threshold:.6f}",
            "- `unknown` は無理に割り当てない低類似レースです。",
            "- クラスタ情報は最終テストでランキング改善が確認されるまで本番利用しません。",
        ]
    )
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--race-dataset", default="data/analysis/race_dataset.csv")
    parser.add_argument("--report-dir", default="reports/research_v2")
    parser.add_argument("--model-dir", default="data/model/research_v2")
    parser.add_argument("--out-dir", default="data/output/research_v2")
    args = parser.parse_args()
    df = pd.read_csv(ROOT / args.race_dataset, low_memory=False)
    report_dir = ROOT / args.report_dir
    model_dir = ROOT / args.model_dir
    out_dir = ROOT / args.out_dir
    coverage_rows = write_coverage_report(df, report_dir / "data_coverage_report.md")
    fit_cluster_model(
        df,
        model_dir / "manshu_cluster_model.pkl",
        report_dir / "manshu_cluster_profiles.csv",
        report_dir / "manshu_cluster_validation.md",
        out_dir / f"manshu_cluster_assignment_{str(df['date'].max()).replace('-', '')}.json",
    )
    (out_dir / "data_coverage_summary.json").write_text(
        json.dumps({"version": "research-v2-coverage-1", "generated_at": now_iso(), "coverage": coverage_rows}, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"coverage_items": len(coverage_rows), "latest_date": str(df["date"].max())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
