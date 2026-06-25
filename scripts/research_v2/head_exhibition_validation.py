#!/usr/bin/env python3
"""Validate head-candidate probabilities and exhibition incrementality."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))

PLACE_ID_TO_JCD = {i: f"{i:02d}" for i in range(1, 25)}

RESULT_COLUMNS = {
    "actual_finish_pos",
    "actual_win",
    "actual_top3",
    "actual_out_top3",
    "result_trifecta",
    "payout_yen",
    "manshu_flag",
    "big_manshu_flag",
    "mid_arare_flag",
    "target_arare_flag",
    "payout_3000_flag",
    "payout_5000_flag",
    "payout_10000_flag",
    "payout_20000_flag",
    "payout_50000_flag",
    "non_target_flag",
}

BASE_FEATURES = [
    "lane",
    "strength_score",
    "start_score",
    "outside_attack_score",
    "stability_score",
    "weakness_score",
    "national_win_rate",
    "local_win_rate",
    "avg_st",
    "motor_quinella_rate",
    "boat_quinella_rate",
    "avg_st_rank",
    "national_win_rank",
    "data_quality_score",
    "national_win_range",
    "lane1_vs_avg_win_diff",
    "lane1_not_a1",
    "lane1_b_class",
    "outer_a_count",
    "outer_motor_strong_flag",
    "outer_exhibition_top_flag",
    "wind_speed_m",
    "wave_cm",
    "early_race",
]

PREVIEW_ONLY_FEATURES = [
    "exhibition_score",
    "exhibition_time",
    "exhibition_rank",
    "exhibition_time_range",
]


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "-", "nan") or pd.isna(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "nan") or pd.isna(value):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def pct(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def race_key(date_text: str, place_id: Any, round_no: Any) -> str:
    jcd = PLACE_ID_TO_JCD.get(as_int(place_id))
    return f"{date_text}_{jcd}_{as_int(round_no):02d}" if jcd else ""


def split_period(date_text: str) -> str:
    if date_text <= "2026-04-30":
        return "train"
    if date_text <= "2026-05-31":
        return "validation"
    return "final_test"


def load_role_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df["date"] = df["date"].astype(str)
    df["period"] = df["date"].map(split_period)
    df["lane"] = pd.to_numeric(df["lane"], errors="coerce").astype("Int64")
    for col in sorted((set(BASE_FEATURES) | set(PREVIEW_ONLY_FEATURES) | {"actual_win"}).intersection(df.columns)):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[df["is_labeled"].astype(int) == 1].copy()


def feature_columns(mode: str) -> list[str]:
    cols = list(BASE_FEATURES)
    if mode == "preview":
        cols += PREVIEW_ONLY_FEATURES
    return cols


def frame_for_model(df: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    cols = [col for col in feature_columns(mode) if col in df.columns and col not in RESULT_COLUMNS]
    x = df[cols].copy()
    x = x.fillna(x.median(numeric_only=True)).fillna(0.0)
    y = df["actual_win"].astype(int)
    return x, y, cols


def fit_candidate_model(df: pd.DataFrame, mode: str) -> tuple[Pipeline, list[str]]:
    train = df[df["period"] == "train"].copy()
    x, y, cols = frame_for_model(train, mode)
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logit",
                LogisticRegression(max_iter=1000, class_weight="balanced", random_state=20260625),
            ),
        ]
    )
    model.fit(x, y)
    return model, cols


def softmax(values: np.ndarray, temperature: float = 18.0) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return values
    centered = (values - np.nanmax(values)) / max(temperature, 1e-6)
    exp = np.exp(centered)
    total = exp.sum()
    return exp / total if total else np.repeat(1 / len(values), len(values))


def normalize_group_probs(scores: pd.Series) -> pd.Series:
    values = scores.fillna(scores.median()).fillna(0.0).to_numpy(dtype=float)
    probs = softmax(values)
    return pd.Series(probs, index=scores.index)


def attach_probabilities(df: pd.DataFrame, mode: str, model: Pipeline, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    score_col = f"head_score_{mode}"
    out[f"baseline_prob_{mode}"] = out.groupby("race_id", group_keys=False)[score_col].apply(normalize_group_probs)
    x = out[cols].copy().fillna(df[cols].median(numeric_only=True)).fillna(0.0)
    raw = model.predict_proba(x)[:, 1]
    out[f"candidate_raw_{mode}"] = raw
    out[f"candidate_prob_{mode}"] = out.groupby("race_id", group_keys=False)[f"candidate_raw_{mode}"].apply(
        lambda s: s / s.sum() if s.sum() else pd.Series(np.repeat(1 / len(s), len(s)), index=s.index)
    )
    return out


def strict_top10_keys(start_date: str, end_date: str) -> set[str]:
    keys: set[str] = set()
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    for path in sorted((ROOT / "data" / "output").glob("boaters_manshu_ranking_*.json")):
        if path.name.startswith("boaters_manshu_ranking_codex_"):
            continue
        compact = path.stem.rsplit("_", 1)[-1]
        if len(compact) != 8 or compact < start or compact > end:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("strict_races") or []
        if not rows:
            rows = payload.get("races") or []
            if rows and not all(str(row.get("ranking_type") or "") == "strict" for row in rows):
                rows = []
        for row in rows[:10]:
            key = race_key(payload.get("date"), row.get("place_id"), row.get("round"))
            if key:
                keys.add(key)
    return keys


def multiclass_metrics(df: pd.DataFrame, prob_col: str) -> dict[str, Any]:
    if df.empty or prob_col not in df:
        return {}
    work = df[["race_id", "actual_win", prob_col]].copy()
    work["actual_win"] = pd.to_numeric(work["actual_win"], errors="coerce").fillna(0).astype(int)
    work[prob_col] = pd.to_numeric(work[prob_col], errors="coerce").fillna(1 / 6).clip(1e-8, 1.0)
    valid_races = work.groupby("race_id", observed=True)["actual_win"].sum()
    valid_races = set(valid_races[valid_races == 1].index)
    work = work[work["race_id"].isin(valid_races)].copy()
    if work.empty:
        return {}
    ordered = work.sort_values(["race_id", prob_col], ascending=[True, False])
    ordered["prob_rank"] = ordered.groupby("race_id", observed=True).cumcount() + 1
    top1 = ordered[ordered["prob_rank"] == 1]
    top2 = ordered[ordered["prob_rank"] <= 2].groupby("race_id", observed=True)["actual_win"].max()
    winners = work[work["actual_win"] == 1]
    work["brier_component"] = (work[prob_col] - work["actual_win"]) ** 2
    brier_by_race = work.groupby("race_id", observed=True)["brier_component"].sum()
    log_loss_by_race = -np.log(winners.set_index("race_id")[prob_col].clip(1e-8, 1.0))
    top_probs = ordered[ordered["prob_rank"].isin([1, 2, 3])].pivot(index="race_id", columns="prob_rank", values=prob_col)
    max_probs = top1[prob_col].tolist()
    top_hits = top1["actual_win"].tolist()
    ece = 0.0
    for lo in np.linspace(0, 1, 6)[:-1]:
        hi = lo + 0.2
        idx = [i for i, value in enumerate(max_probs) if lo <= value < hi or (hi == 1 and value <= hi)]
        if not idx:
            continue
        conf = float(np.mean([max_probs[i] for i in idx]))
        acc = float(np.mean([top_hits[i] for i in idx]))
        ece += len(idx) / len(top_hits) * abs(acc - conf)
    gap_1_2 = top_probs[1] - top_probs[2] if 1 in top_probs and 2 in top_probs else pd.Series(dtype=float)
    gap_2_3 = top_probs[2] - top_probs[3] if 2 in top_probs and 3 in top_probs else pd.Series(dtype=float)
    return {
        "race_count": int(len(top_hits)),
        "top1_hit_rate_pct": pct(sum(top_hits), len(top_hits)),
        "top2_capture_rate_pct": pct(float(top2.sum()), len(top2)),
        "brier_score": round(float(brier_by_race.mean()), 6),
        "log_loss": round(float(log_loss_by_race.mean()), 6),
        "calibration_error": round(ece, 6),
        "avg_gap_1_2_pct": round(float(gap_1_2.mean()) * 100, 3) if not gap_1_2.empty else None,
        "avg_gap_2_3_pct": round(float(gap_2_3.mean()) * 100, 3) if not gap_2_3.empty else None,
    }


def evaluate(df: pd.DataFrame, top10_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in ["train", "validation", "final_test"]:
        period_df = df[df["period"] == period]
        for scope, scoped in [
            ("all_labeled", period_df),
            ("strict_top10", period_df[period_df["race_id"].isin(top10_keys)]),
        ]:
            for mode in ["morning", "preview"]:
                for model_name, prob_col in [
                    ("existing_role_softmax", f"baseline_prob_{mode}"),
                    ("candidate_logit_v1", f"candidate_prob_{mode}"),
                ]:
                    metrics = multiclass_metrics(scoped, prob_col)
                    if not metrics:
                        continue
                    rows.append({"period": period, "scope": scope, "mode": mode, "model": model_name, **metrics})
    return rows


def feature_importance(model: Pipeline, cols: list[str], mode: str) -> list[dict[str, Any]]:
    logit = model.named_steps["logit"]
    coefs = logit.coef_[0]
    rows = []
    for name, coef in sorted(zip(cols, coefs), key=lambda item: abs(item[1]), reverse=True):
        rows.append({"mode": mode, "feature": name, "coefficient": round(float(coef), 6), "abs_coefficient": round(abs(float(coef)), 6)})
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def latest_head_predictions(df: pd.DataFrame, date_text: str) -> dict[str, Any]:
    day = df[df["date"] == date_text].copy()
    races = []
    for race_id, group in day.groupby("race_id"):
        ordered = group.sort_values("candidate_prob_preview", ascending=False)
        boats = []
        for _idx, row in group.sort_values("lane").iterrows():
            lane = as_int(row.get("lane"))
            missing = []
            for col in feature_columns("preview"):
                if col in group.columns and pd.isna(row.get(col)):
                    missing.append(col)
            boats.append(
                {
                    "lane": lane,
                    "name": row.get("name"),
                    "win_probability_pct": round(float(row["candidate_prob_preview"]) * 100, 2),
                    "morning_probability_pct": round(float(row["candidate_prob_morning"]) * 100, 2),
                    "preview_probability_pct": round(float(row["candidate_prob_preview"]) * 100, 2),
                    "exhibition_delta_pct": round((float(row["candidate_prob_preview"]) - float(row["candidate_prob_morning"])) * 100, 2),
                    "win_rank": int(ordered.index.get_loc(row.name) + 1) if row.name in ordered.index else None,
                    "head_candidate": bool(lane in [as_int(v) for v in ordered.head(2)["lane"].tolist()]),
                    "confidence": "low" if float(ordered.iloc[1]["candidate_prob_preview"] - ordered.iloc[2]["candidate_prob_preview"]) < 0.02 else "normal",
                    "available_features": [col for col in feature_columns("preview") if col in group.columns and not pd.isna(row.get(col))],
                    "missing_features": missing,
                    "reason": row.get("head_reasons") or "candidate_logit_v1",
                }
            )
        races.append(
            {
                "race_id": race_id,
                "date": group.iloc[0]["date"],
                "venue_name": group.iloc[0]["venue_name"],
                "race_no": as_int(group.iloc[0]["race_no"]),
                "deadline": group.iloc[0].get("deadline"),
                "head_spread_too_wide": bool(float(ordered.iloc[1]["candidate_prob_preview"] - ordered.iloc[2]["candidate_prob_preview"]) < 0.02) if len(ordered) >= 3 else True,
                "boats": boats,
            }
        )
    return {
        "version": "research-v2-head-prediction-1",
        "date": date_text,
        "generated_at": now_iso(),
        "model_version": "candidate_logit_v1",
        "probability_note": "6艇の候補ロジットをレース内で正規化し、合計100%に校正。",
        "races": sorted(races, key=lambda row: (row["venue_name"], row["race_no"])),
    }


def exhibition_adjustments(df: pd.DataFrame, ranking_date: str) -> dict[str, Any]:
    compact = ranking_date.replace("-", "")
    ranking_path = ROOT / "data" / "output" / f"boaters_manshu_ranking_{compact}.json"
    ranking_payload = json.loads(ranking_path.read_text(encoding="utf-8")) if ranking_path.exists() else {}
    rows = []
    for row in ranking_payload.get("strict_races") or ranking_payload.get("races") or []:
        metrics = row.get("metrics") or {}
        base = as_float(row.get("base_manshu_rate_pct"))
        current = as_float(row.get("manshu_rate_pct"))
        rows.append(
            {
                "rank": row.get("rank"),
                "place_name": row.get("place_name"),
                "round": row.get("round"),
                "morning_manshu_probability_pct": base,
                "preview_manshu_probability_pct": current,
                "exhibition_adjustment_pct": round((current or 0) - (base or 0), 2) if base is not None and current is not None else None,
                "used_exhibition": {
                    "tenji_boats": metrics.get("tenji_boats"),
                    "isshu_boats": metrics.get("isshu_boats"),
                    "double_time_boats": metrics.get("double_time_boats"),
                    "super_slit_boats": metrics.get("super_slit_boats"),
                    "slit_shape_label": metrics.get("slit_shape_label"),
                },
                "missing_warning": "preview_data_missing" if not metrics.get("tenji_boats") else "",
                "race_deadline": row.get("deadline_time"),
                "fetched_at": ranking_payload.get("generated_at"),
                "available_at": ranking_payload.get("generated_at"),
                "source": ranking_path.as_posix(),
                "schema_version": "research-v2-exhibition-1",
            }
        )
    return {
        "version": "research-v2-exhibition-adjustment-1",
        "date": ranking_date,
        "generated_at": now_iso(),
        "source_ranking": ranking_path.as_posix(),
        "fallback_rule": "展示情報が欠損する場合は朝版相当のbase_manshu_rate_pctを参照し、0埋めしない。",
        "races": rows,
    }


def write_reports(validation_rows: list[dict[str, Any]], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    def find(period: str, scope: str, mode: str, model: str) -> dict[str, Any]:
        for row in validation_rows:
            if row["period"] == period and row["scope"] == scope and row["mode"] == mode and row["model"] == model:
                return row
        return {}
    final_morning = find("final_test", "strict_top10", "morning", "candidate_logit_v1")
    final_preview = find("final_test", "strict_top10", "preview", "candidate_logit_v1")
    baseline_preview = find("final_test", "strict_top10", "preview", "existing_role_softmax")
    text = [
        "# research_v2 Head Model Validation",
        "",
        "既存 `head/axis/toss/opponent` は基準として保持し、別系統の候補 `candidate_logit_v1` を比較しました。本番ランキングには接続していません。",
        "",
        "## 最終テスト strict TOP10",
        "",
        f"- 既存role直前 head2捕捉率: {baseline_preview.get('top2_capture_rate_pct')}%",
        f"- 候補logit朝 head2捕捉率: {final_morning.get('top2_capture_rate_pct')}%",
        f"- 候補logit直前 head2捕捉率: {final_preview.get('top2_capture_rate_pct')}%",
        f"- 候補logit直前 Brier: {final_preview.get('brier_score')}",
        f"- 候補logit直前 log loss: {final_preview.get('log_loss')}",
        "",
        "## 判定",
        "",
        "- この段階では本番採用しません。TOP10内で候補が既存roleを安定して上回るか、前向き検証が必要です。",
        "- 結果列、払戻、人気、決まり手は特徴量に入れていません。",
    ]
    (report_dir / "head_model_validation.md").write_text("\n".join(text) + "\n", encoding="utf-8")

    ex_text = [
        "# research_v2 Exhibition Incremental Validation",
        "",
        "朝版と直前版を分離し、展示補正後の頭候補精度を比較しました。",
        "",
        "## strict TOP10 / final_test / candidate_logit_v1",
        "",
        f"- 朝版 head2捕捉率: {final_morning.get('top2_capture_rate_pct')}%",
        f"- 直前版 head2捕捉率: {final_preview.get('top2_capture_rate_pct')}%",
        f"- 朝版 Brier: {final_morning.get('brier_score')}",
        f"- 直前版 Brier: {final_preview.get('brier_score')}",
        "",
        "## 採用方針",
        "",
        "- 直前版が朝版より悪化したセグメントでは展示補正を採用しません。",
        "- 欠損展示データは0ではなく欠損として扱い、朝版へフォールバックします。",
    ]
    (report_dir / "exhibition_incremental_validation.md").write_text("\n".join(ex_text) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-dataset", default="data/analysis/boat_role_dataset.csv")
    parser.add_argument("--out-dir", default="data/output/research_v2")
    parser.add_argument("--model-dir", default="data/model/research_v2")
    parser.add_argument("--report-dir", default="reports/research_v2")
    parser.add_argument("--ranking-start-date", default="2026-05-01")
    parser.add_argument("--ranking-end-date", default="2026-06-25")
    args = parser.parse_args()

    df = load_role_dataset(ROOT / args.role_dataset)
    models: dict[str, Pipeline] = {}
    cols_by_mode: dict[str, list[str]] = {}
    for mode in ["morning", "preview"]:
        model, cols = fit_candidate_model(df, mode)
        models[mode] = model
        cols_by_mode[mode] = cols
        df = attach_probabilities(df, mode, model, cols)
    top10_keys = strict_top10_keys(args.ranking_start_date, args.ranking_end_date)
    validation_rows = evaluate(df, top10_keys)
    importance_rows = []
    for mode in ["morning", "preview"]:
        importance_rows.extend(feature_importance(models[mode], cols_by_mode[mode], mode))

    out_dir = ROOT / args.out_dir
    model_dir = ROOT / args.model_dir
    report_dir = ROOT / args.report_dir
    write_csv(report_dir / "head_model_validation.csv", validation_rows)
    write_csv(report_dir / "exhibition_incremental_validation.csv", validation_rows)
    write_csv(report_dir / "head_feature_importance.csv", importance_rows)
    write_reports(validation_rows, report_dir)
    latest_date = str(df["date"].max())
    (out_dir / f"head_prediction_{latest_date.replace('-', '')}.json").write_text(
        json.dumps(latest_head_predictions(df, latest_date), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / f"exhibition_adjustment_{args.ranking_end_date.replace('-', '')}.json").write_text(
        json.dumps(exhibition_adjustments(df, args.ranking_end_date), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    model_dir.mkdir(parents=True, exist_ok=True)
    with (model_dir / "head_candidate_logit_v1.pkl").open("wb") as handle:
        pickle.dump({"models": models, "features": cols_by_mode, "created_at": now_iso()}, handle)
    print(json.dumps({"validation_rows": len(validation_rows), "feature_rows": len(importance_rows), "latest_date": latest_date}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
