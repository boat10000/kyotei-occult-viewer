#!/usr/bin/env python3
"""Validate lightweight manshu prediction models with a time split."""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


MORNING_FEATURES = [
    "race_no",
    "early_race",
    "morning_flag",
    "night_flag",
    "lane1_b_class",
    "lane1_not_a1",
    "lane1_national_win_rate",
    "lane1_local_win_rate",
    "lane1_vs_avg_win_diff",
    "lane1_vs_best_outer_win_diff",
    "a1_count",
    "a2_count",
    "b_count",
    "outer_a_count",
    "outer_a1_count",
    "national_win_range",
    "local_win_range",
    "motor_quinella_range",
    "outer_motor_strong_flag",
]

PREVIEW_FEATURES = MORNING_FEATURES + [
    "wind_speed_m",
    "wave_cm",
    "lane1_exhibition_rank4plus",
    "outer_exhibition_top_flag",
    "outer_exhibition_beats_lane1",
    "exhibition_time_range",
]

LEAKAGE_COLUMNS = [
    "payout_yen",
    "manshu_flag",
    "big_manshu_flag",
    "result_trifecta",
    "popularity",
    "decision",
]


def as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any, default: int = 0) -> int:
    f = as_float(value)
    return int(f) if f is not None else default


def sigmoid(value: float) -> float:
    if value < -40:
        return 0.0
    if value > 40:
        return 1.0
    return 1.0 / (1.0 + math.exp(-value))


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if as_int(row.get("valid_for_analysis")) == 1]


def time_split(rows: list[dict[str, Any]], ratio: float = 0.7) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({row["date"] for row in rows})
    if len(dates) <= 1:
        return rows, []
    cut = max(1, min(len(dates) - 1, int(len(dates) * ratio)))
    train_dates = set(dates[:cut])
    return [row for row in rows if row["date"] in train_dates], [row for row in rows if row["date"] not in train_dates]


def prepare_matrix(
    train: list[dict[str, Any]], valid: list[dict[str, Any]], features: list[str]
) -> tuple[list[list[float]], list[int], list[list[float]], list[int], dict[str, tuple[float, float]]]:
    stats: dict[str, tuple[float, float]] = {}
    for feature in features:
        values = [as_float(row.get(feature)) for row in train]
        clean = [value for value in values if value is not None]
        mean = sum(clean) / len(clean) if clean else 0.0
        variance = sum((value - mean) ** 2 for value in clean) / len(clean) if clean else 0.0
        std = math.sqrt(variance) if variance > 0 else 1.0
        stats[feature] = (mean, std)

    def transform(rows: list[dict[str, Any]]) -> list[list[float]]:
        matrix = []
        for row in rows:
            values = [1.0]
            for feature in features:
                mean, std = stats[feature]
                value = as_float(row.get(feature))
                values.append(((value if value is not None else mean) - mean) / std)
            matrix.append(values)
        return matrix

    y_train = [as_int(row.get("manshu_flag")) for row in train]
    y_valid = [as_int(row.get("manshu_flag")) for row in valid]
    return transform(train), y_train, transform(valid), y_valid, stats


def fit_logistic(x: list[list[float]], y: list[int], epochs: int = 1200, lr: float = 0.05, l2: float = 0.02) -> list[float]:
    if not x:
        return []
    weights = [0.0 for _ in range(len(x[0]))]
    prevalence = sum(y) / len(y) if y else 0.1
    prevalence = min(max(prevalence, 1e-4), 1 - 1e-4)
    weights[0] = math.log(prevalence / (1 - prevalence))
    for _epoch in range(epochs):
        gradients = [0.0 for _ in weights]
        for row, target in zip(x, y):
            pred = sigmoid(sum(weight * value for weight, value in zip(weights, row)))
            error = pred - target
            for idx, value in enumerate(row):
                gradients[idx] += error * value
        for idx in range(len(weights)):
            penalty = 0.0 if idx == 0 else l2 * weights[idx]
            weights[idx] -= lr * ((gradients[idx] / len(x)) + penalty)
    return weights


def predict(x: list[list[float]], weights: list[float]) -> list[float]:
    return [sigmoid(sum(weight * value for weight, value in zip(weights, row))) for row in x]


def roc_auc(y: list[int], pred: list[float]) -> float | None:
    pairs = sorted(zip(pred, y), key=lambda item: item[0])
    pos = sum(y)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum = 0.0
    for rank, (_score, target) in enumerate(pairs, start=1):
        if target:
            rank_sum += rank
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def pr_auc(y: list[int], pred: list[float]) -> float | None:
    if sum(y) == 0:
        return None
    pairs = sorted(zip(pred, y), key=lambda item: item[0], reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    area = 0.0
    total_pos = sum(y)
    for _score, target in pairs:
        if target:
            tp += 1
        else:
            fp += 1
        recall = tp / total_pos
        precision = tp / (tp + fp)
        area += precision * max(0.0, recall - prev_recall)
        prev_recall = recall
    return area


def log_loss(y: list[int], pred: list[float]) -> float | None:
    if not y:
        return None
    eps = 1e-8
    return -sum(target * math.log(max(eps, p)) + (1 - target) * math.log(max(eps, 1 - p)) for target, p in zip(y, pred)) / len(y)


def brier(y: list[int], pred: list[float]) -> float | None:
    if not y:
        return None
    return sum((target - p) ** 2 for target, p in zip(y, pred)) / len(y)


def precision_at_k_by_day(rows: list[dict[str, Any]], pred: list[float], k: int) -> tuple[int, int, float | None]:
    groups: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    for row, score in zip(rows, pred):
        groups[row["date"]].append((score, row))
    selected: list[dict[str, Any]] = []
    for day_rows in groups.values():
        selected.extend(row for _score, row in sorted(day_rows, key=lambda item: item[0], reverse=True)[:k])
    manshu = sum(as_int(row.get("manshu_flag")) for row in selected)
    return len(selected), manshu, manshu / len(selected) if selected else None


def calibration_bins(y: list[int], pred: list[float], bins: int = 5) -> list[tuple[int, float, float]]:
    if not y:
        return []
    ordered = sorted(zip(pred, y), key=lambda item: item[0])
    size = max(1, math.ceil(len(ordered) / bins))
    output = []
    for start in range(0, len(ordered), size):
        chunk = ordered[start : start + size]
        output.append((len(chunk), sum(score for score, _target in chunk) / len(chunk), sum(target for _score, target in chunk) / len(chunk)))
    return output


def evaluate_model(name: str, train: list[dict[str, Any]], valid: list[dict[str, Any]], features: list[str]) -> dict[str, Any]:
    x_train, y_train, x_valid, y_valid, _stats = prepare_matrix(train, valid, features)
    weights = fit_logistic(x_train, y_train)
    train_pred = predict(x_train, weights)
    valid_pred = predict(x_valid, weights)
    return {
        "name": name,
        "features": features,
        "weights": weights,
        "train_pred": train_pred,
        "valid_pred": valid_pred,
        "train_y": y_train,
        "valid_y": y_valid,
        "train_metrics": metrics(y_train, train_pred),
        "valid_metrics": metrics(y_valid, valid_pred),
        "importance": sorted(
            [{"feature": feature, "coefficient": weights[idx + 1], "abs_coefficient": abs(weights[idx + 1])} for idx, feature in enumerate(features)],
            key=lambda item: item["abs_coefficient"],
            reverse=True,
        ),
        "calibration": calibration_bins(y_valid, valid_pred),
    }


def metrics(y: list[int], pred: list[float]) -> dict[str, float | None]:
    return {
        "roc_auc": roc_auc(y, pred),
        "pr_auc": pr_auc(y, pred),
        "brier": brier(y, pred),
        "log_loss": log_loss(y, pred),
    }


def existing_score_metrics(valid: list[dict[str, Any]]) -> list[str]:
    scored = [row for row in valid if row.get("existing_score") not in (None, "")]
    if not scored:
        return ["- 既存スコア: 検証期間に結合可能な行なし。"]
    lines = ["| 既存スコア | 選択数 | 万舟数 | 万舟率 |", "|---|---:|---:|---:|"]
    for k in [3, 5, 10]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in scored:
            groups[row["date"]].append(row)
        selected = []
        for day_rows in groups.values():
            selected.extend(sorted(day_rows, key=lambda row: as_float(row.get("existing_score")) or -999, reverse=True)[:k])
        manshu = sum(as_int(row.get("manshu_flag")) for row in selected)
        rate = manshu / len(selected) if selected else 0
        lines.append(f"| Top{k}/day | {len(selected)} | {manshu} | {rate*100:.2f}% |")
    return lines


def write_report(path: Path, rows: list[dict[str, Any]], train: list[dict[str, Any]], valid: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    train_base = sum(as_int(row.get("manshu_flag")) for row in train) / len(train) if train else 0
    valid_base = sum(as_int(row.get("manshu_flag")) for row in valid) / len(valid) if valid else 0
    lines = [
        "# Manshu Model Validation",
        "",
        "この検証は荒れやすさの研究用であり、舟券購入や利益を推奨・保証するものではありません。",
        "",
        "## 分割",
        "",
        f"- 全体レース数: {len(rows)}",
        f"- 学習期間レース数: {len(train)} / 万舟率 {train_base*100:.2f}%",
        f"- 検証期間レース数: {len(valid)} / 万舟率 {valid_base*100:.2f}%",
        "- 日付順の時系列分割。日付をシャッフルしていない。",
        "",
        "## データリーク除外",
        "",
    ]
    lines.extend(f"- `{column}` は特徴量に入れない。" for column in LEAKAGE_COLUMNS)
    for result in results:
        lines.extend(
            [
                "",
                f"## {result['name']}",
                "",
                "| split | ROC-AUC | PR-AUC | Brier | log loss |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for split_name in ["train", "valid"]:
            metric = result[f"{split_name}_metrics"]
            lines.append(
                "| {split} | {roc} | {pr} | {brier} | {loss} |".format(
                    split=split_name,
                    roc=f"{metric['roc_auc']:.3f}" if metric["roc_auc"] is not None else "",
                    pr=f"{metric['pr_auc']:.3f}" if metric["pr_auc"] is not None else "",
                    brier=f"{metric['brier']:.3f}" if metric["brier"] is not None else "",
                    loss=f"{metric['log_loss']:.3f}" if metric["log_loss"] is not None else "",
                )
            )
        lines.extend(["", "### precision@K/day", "", "| K | 選択数 | 万舟数 | 万舟率 |", "|---:|---:|---:|---:|"])
        for k in [3, 5, 10]:
            selected, manshu, rate = precision_at_k_by_day(valid, result["valid_pred"], k)
            lines.append(f"| {k} | {selected} | {manshu} | {(rate or 0)*100:.2f}% |")
        lines.extend(["", "### 重要特徴量（係数絶対値上位）", "", "| feature | coefficient |", "|---|---:|"])
        for item in result["importance"][:12]:
            lines.append(f"| `{item['feature']}` | {item['coefficient']:.3f} |")
        lines.extend(["", "### calibration", "", "| bin件数 | 平均予測確率 | 実測万舟率 |", "|---:|---:|---:|"])
        for n, pred_mean, actual in result["calibration"]:
            lines.append(f"| {n} | {pred_mean*100:.2f}% | {actual*100:.2f}% |")
    lines.extend(["", "## 既存スコア比較", ""])
    lines.extend(existing_score_metrics(valid))
    lines.extend(
        [
            "",
            "## 解釈上の注意",
            "",
            "- モデル指標はサンプル期間に依存する。短期間では信頼区間が広い。",
            "- 直前版モデルは展示・気象を使うため、朝版の予測ロジックとは分ける。",
            "- 結果後にしか分からない項目は特徴量から除外済み。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.dataset))
    if not rows:
        raise SystemExit("dataset has no valid rows")
    train, valid = time_split(rows) if args.time_split else (rows, rows)
    if not valid:
        valid = train
    results = [
        evaluate_model("朝版ロジスティック回帰", train, valid, MORNING_FEATURES),
        evaluate_model("直前版ロジスティック回帰", train, valid, PREVIEW_FEATURES),
    ]
    write_report(Path(args.report), rows, train, valid, results)
    print(f"wrote {args.report}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/analysis/race_dataset.csv")
    parser.add_argument("--time-split", action="store_true")
    parser.add_argument("--report", default="reports/model_validation.md")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

