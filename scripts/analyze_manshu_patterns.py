#!/usr/bin/env python3
"""Analyze manshu common patterns from a race-level dataset."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


Row = dict[str, Any]
Predicate = Callable[[Row], bool]


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def read_rows(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def wilson_ci(success: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = success / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def p_value(success: int, total: int, baseline_rate: float) -> float | None:
    if total == 0 or baseline_rate in (0, 1):
        return None
    p = success / total
    se = math.sqrt(baseline_rate * (1 - baseline_rate) / total)
    if se == 0:
        return None
    z = (p - baseline_rate) / se
    return 2 * (1 - normal_cdf(abs(z)))


def stats_for_rows(rows: list[Row], baseline_rate: float, total_label: str = "") -> dict[str, Any]:
    n = len(rows)
    manshu = sum(as_int(row.get("manshu_flag")) for row in rows)
    payouts = [as_int(row.get("payout_yen")) for row in rows if row.get("payout_yen") not in (None, "")]
    rate = manshu / n if n else 0.0
    ci_low, ci_high = wilson_ci(manshu, n)
    return {
        "n": n,
        "manshu_n": manshu,
        "manshu_rate": rate,
        "diff_vs_baseline": rate - baseline_rate,
        "lift": rate / baseline_rate if baseline_rate else None,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "p_value": p_value(manshu, n, baseline_rate),
        "mean_payout": statistics.fmean(payouts) if payouts else None,
        "median_payout": statistics.median(payouts) if payouts else None,
        "max_payout": max(payouts) if payouts else None,
        "label": total_label,
    }


def time_split(rows: list[Row], train_ratio: float = 0.7) -> tuple[list[Row], list[Row]]:
    dates = sorted({row["date"] for row in rows})
    if len(dates) <= 1:
        return rows, []
    cut_index = max(1, min(len(dates) - 1, int(len(dates) * train_ratio)))
    train_dates = set(dates[:cut_index])
    return [row for row in rows if row["date"] in train_dates], [row for row in rows if row["date"] not in train_dates]


def format_pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value) * 100:.2f}%"


def format_num(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.{digits}f}"


def group_conditions(rows: list[Row], fields: list[str], baseline_rate: float, min_count: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for field in fields:
        groups: dict[str, list[Row]] = defaultdict(list)
        for row in rows:
            value = row.get(field)
            label = str(value) if value not in (None, "") else "missing"
            groups[label].append(row)
        for label, group_rows in groups.items():
            if len(group_rows) < min_count:
                continue
            stat = stats_for_rows(group_rows, baseline_rate)
            stat.update(
                {
                    "condition_type": "single",
                    "condition_name": f"{field} = {label}",
                    "feature": field,
                    "value": label,
                    "notes": "",
                    "priority": "参考" if stat["lift"] and stat["lift"] < 1.15 else "中",
                }
            )
            output.append(stat)
    return output


def condition_definitions() -> list[tuple[str, Predicate, str, str]]:
    return [
        (
            "1号艇B級 × B級4人以上 × 1R〜4R",
            lambda r: as_int(r.get("lane1_b_class")) == 1 and as_int(r.get("b_count")) >= 4 and as_int(r.get("early_race")) == 1,
            "朝版",
            "低勝率インとB級多数の早いレース。件数不足なら参考。",
        ),
        (
            "1号艇A2以下 × 外枠A1あり × 風速5m以上",
            lambda r: as_int(r.get("lane1_a2_or_lower")) == 1
            and as_int(r.get("outer_a1_count")) >= 1
            and (as_float(r.get("wind_speed_m")) or 0) >= 5,
            "直前版",
            "風は直前/結果側の気象なので朝版には使わない。",
        ),
        (
            "1号艇勝率5.0未満 × 勝率レンジ1.5以内",
            lambda r: (as_float(r.get("lane1_national_win_rate")) or 99) < 5.0
            and (as_float(r.get("national_win_range")) or 99) <= 1.5,
            "朝版",
            "低いインが横一線の混戦に入る条件。",
        ),
        (
            "1号艇展示4位以下 × 外枠展示上位あり",
            lambda r: as_int(r.get("lane1_exhibition_rank4plus")) == 1 and as_int(r.get("outer_exhibition_top_flag")) == 1,
            "直前版",
            "展示は締切前に分かるが朝版には入れない。",
        ),
        (
            "1号艇展示劣勢 × 外枠が1号艇より展示上位",
            lambda r: as_int(r.get("outer_exhibition_beats_lane1")) == 1 and as_int(r.get("lane1_exhibition_rank4plus")) == 1,
            "直前版",
            "展示順位の相対比較。",
        ),
        (
            "早いレース × B級3人以上",
            lambda r: as_int(r.get("early_race")) == 1 and as_int(r.get("b_count")) >= 3,
            "朝版",
            "1R〜4Rの番組構成に着目。",
        ),
        (
            "戸田/江戸川/平和島 × 外枠A級あり",
            lambda r: str(r.get("jcd")).zfill(2) in {"02", "03", "04"} and as_int(r.get("outer_a_count")) >= 1,
            "朝版",
            "場特性と外枠実力者の組み合わせ。",
        ),
        (
            "ナイター/ミッドナイト × 低勝率イン × 混戦",
            lambda r: str(r.get("time_zone")) in {"night", "midnight"}
            and (as_float(r.get("lane1_national_win_rate")) or 99) < 5.5
            and (as_float(r.get("national_win_range")) or 99) <= 2.0,
            "朝版",
            "時間帯は締切予定から作るため朝版でも使用可。",
        ),
        (
            "外枠A級2人以上 × 1号艇A1でない",
            lambda r: as_int(r.get("outer_a_count")) >= 2 and as_int(r.get("lane1_not_a1")) == 1,
            "朝版",
            "イン弱め、外枠実力厚め。",
        ),
        (
            "外枠モーター強者あり × 1号艇A1でない",
            lambda r: as_int(r.get("outer_motor_strong_flag")) == 1 and as_int(r.get("lane1_not_a1")) == 1,
            "朝版",
            "モーター2連率40%以上を強めの代理指標にした条件。",
        ),
    ]


def compound_conditions(rows: list[Row], baseline_rate: float, train: list[Row], valid: list[Row], min_count: int) -> list[dict[str, Any]]:
    valid_baseline = sum(as_int(row.get("manshu_flag")) for row in valid) / len(valid) if valid else 0.0
    output: list[dict[str, Any]] = []
    for name, predicate, phase, notes in condition_definitions():
        matched = [row for row in rows if predicate(row)]
        if len(matched) < max(1, min_count // 2):
            continue
        stat = stats_for_rows(matched, baseline_rate)
        train_rows = [row for row in train if predicate(row)]
        valid_rows = [row for row in valid if predicate(row)]
        train_stat = stats_for_rows(train_rows, baseline_rate)
        valid_stat = stats_for_rows(valid_rows, valid_baseline) if valid else stats_for_rows([], baseline_rate)
        reproducibility = "参考"
        if len(valid_rows) >= min_count and valid_stat["manshu_rate"] >= valid_baseline and stat["lift"] and stat["lift"] >= 1.15:
            reproducibility = "再現あり"
        elif len(valid_rows) < min_count:
            reproducibility = "検証件数不足"
        elif valid_stat["manshu_rate"] < valid_baseline:
            reproducibility = "検証で低下"
        priority = "高" if reproducibility == "再現あり" and stat["lift"] and stat["lift"] >= 1.5 else "中" if stat["lift"] and stat["lift"] >= 1.2 else "参考"
        stat.update(
            {
                "condition_type": "compound",
                "condition_name": name,
                "feature": phase,
                "value": "",
                "train_n": train_stat["n"],
                "train_rate": train_stat["manshu_rate"],
                "valid_n": valid_stat["n"],
                "valid_rate": valid_stat["manshu_rate"],
                "reproducibility": reproducibility,
                "priority": priority,
                "notes": notes,
            }
        )
        output.append(stat)
    return output


def add_validation_to_singles(singles: list[dict[str, Any]], train: list[Row], valid: list[Row], baseline_rate: float) -> None:
    valid_baseline = sum(as_int(row.get("manshu_flag")) for row in valid) / len(valid) if valid else baseline_rate
    for stat in singles:
        field = stat["feature"]
        value = stat["value"]
        pred = lambda r, field=field, value=value: (str(r.get(field)) if r.get(field) not in (None, "") else "missing") == value
        train_rows = [row for row in train if pred(row)]
        valid_rows = [row for row in valid if pred(row)]
        train_stat = stats_for_rows(train_rows, baseline_rate)
        valid_stat = stats_for_rows(valid_rows, valid_baseline) if valid else stats_for_rows([], baseline_rate)
        stat["train_n"] = train_stat["n"]
        stat["train_rate"] = train_stat["manshu_rate"]
        stat["valid_n"] = valid_stat["n"]
        stat["valid_rate"] = valid_stat["manshu_rate"]
        if not valid:
            stat["reproducibility"] = "検証不可"
        elif valid_stat["n"] < 10:
            stat["reproducibility"] = "検証件数不足"
        elif valid_stat["manshu_rate"] >= valid_baseline:
            stat["reproducibility"] = "再現あり"
        else:
            stat["reproducibility"] = "検証で低下"


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "condition_type",
        "condition_name",
        "feature",
        "value",
        "n",
        "manshu_n",
        "manshu_rate",
        "diff_vs_baseline",
        "lift",
        "ci95_low",
        "ci95_high",
        "p_value",
        "mean_payout",
        "median_payout",
        "max_payout",
        "train_n",
        "train_rate",
        "valid_n",
        "valid_rate",
        "reproducibility",
        "priority",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})


def candidate_score(row: Row) -> int:
    score = 0
    score += 3 * as_int(row.get("lane1_b_class"))
    score += 1 * as_int(row.get("lane1_not_a1"))
    score += 1 * as_int(row.get("early_race"))
    score += 2 if as_int(row.get("outer_a_count")) >= 1 else 0
    score += 2 * as_int(row.get("lane1_exhibition_rank4plus"))
    score += 2 * as_int(row.get("outer_exhibition_top_flag"))
    score += 1 if as_int(row.get("b_count")) >= 4 else 0
    score += 1 if (as_float(row.get("wind_speed_m")) or 0) >= 5 else 0
    score += 1 if str(row.get("jcd")).zfill(2) in {"02", "03", "04"} else 0
    score += 1 if (as_float(row.get("national_win_range")) or 99) <= 1.5 else 0
    return score


def topk_by_day(rows: list[Row], key: str, k: int, generated: bool = False) -> dict[str, Any]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        score = candidate_score(row) if generated else as_float(row.get(key))
        if score is None:
            continue
        copied = dict(row)
        copied["_score"] = score
        groups[row["date"]].append(copied)
    selected: list[Row] = []
    for day_rows in groups.values():
        selected.extend(sorted(day_rows, key=lambda row: row["_score"], reverse=True)[:k])
    manshu = sum(as_int(row.get("manshu_flag")) for row in selected)
    return {
        "k": k,
        "selected": len(selected),
        "manshu_n": manshu,
        "manshu_rate": manshu / len(selected) if selected else None,
    }


def markdown_table(rows: list[dict[str, Any]], limit: int = 10) -> list[str]:
    lines = ["| 条件 | 件数 | 万舟数 | 万舟率 | 差分 | リフト | 検証 | 優先度 |", "|---|---:|---:|---:|---:|---:|---|---|"]
    for row in rows[:limit]:
        lines.append(
            "| {name} | {n} | {m} | {rate} | {diff} | {lift} | {valid} | {priority} |".format(
                name=row.get("condition_name", ""),
                n=row.get("n", 0),
                m=row.get("manshu_n", 0),
                rate=format_pct(row.get("manshu_rate")),
                diff=format_pct(row.get("diff_vs_baseline")),
                lift=format_num(row.get("lift")),
                valid=format_pct(row.get("valid_rate")) if row.get("valid_n") else row.get("reproducibility", ""),
                priority=row.get("priority", ""),
            )
        )
    return lines


def write_markdown(path: Path, rows: list[Row], conditions: list[dict[str, Any]], singles: list[dict[str, Any]], compounds: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dates = sorted({row["date"] for row in rows})
    baseline = sum(as_int(row.get("manshu_flag")) for row in rows) / len(rows) if rows else 0
    manshu = sum(as_int(row.get("manshu_flag")) for row in rows)
    grade_counts: dict[str, list[Row]] = defaultdict(list)
    venue_counts: dict[str, list[Row]] = defaultdict(list)
    race_counts: dict[str, list[Row]] = defaultdict(list)
    time_counts: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grade_counts[str(row.get("grade") or "missing")].append(row)
        venue_counts[str(row.get("venue_name") or row.get("jcd") or "missing")].append(row)
        race_counts[str(row.get("race_no") or "missing")].append(row)
        time_counts[str(row.get("time_zone") or "missing")].append(row)

    def summary_lines(groups: dict[str, list[Row]], limit: int = 8) -> list[str]:
        scored = []
        for label, group in groups.items():
            stat = stats_for_rows(group, baseline)
            scored.append((label, stat))
        scored.sort(key=lambda item: (-item[1]["manshu_rate"], -item[1]["n"]))
        lines = ["| 区分 | 件数 | 万舟数 | 万舟率 |", "|---|---:|---:|---:|"]
        for label, stat in scored[:limit]:
            lines.append(f"| {label} | {stat['n']} | {stat['manshu_n']} | {format_pct(stat['manshu_rate'])} |")
        return lines

    positive_singles = sorted([row for row in singles if (row.get("diff_vs_baseline") or 0) > 0], key=lambda row: (row.get("lift") or 0, row.get("n") or 0), reverse=True)
    low_singles = sorted([row for row in singles if (row.get("diff_vs_baseline") or 0) < 0], key=lambda row: row.get("manshu_rate") or 0)
    positive_compounds = sorted(compounds, key=lambda row: (row.get("priority") == "高", row.get("lift") or 0, row.get("n") or 0), reverse=True)
    weak_but_interesting = [row for row in compounds if row.get("n", 0) < 30 or row.get("reproducibility") == "検証件数不足"]

    existing_available = any(row.get("existing_score") not in (None, "") for row in rows)
    top_lines = ["| 指標 | Top3 | Top5 | Top10 |", "|---|---:|---:|---:|"]
    if existing_available:
        existing = [topk_by_day(rows, "existing_score", k) for k in [3, 5, 10]]
        top_lines.append("| 既存スコア | " + " | ".join(format_pct(item["manshu_rate"]) for item in existing) + " |")
    generated = [topk_by_day(rows, "candidate_score", k, generated=True) for k in [3, 5, 10]]
    top_lines.append("| 分析候補スコア | " + " | ".join(format_pct(item["manshu_rate"]) for item in generated) + " |")

    lines = [
        "# 万舟レース共通条件分析レポート",
        "",
        "このレポートは娯楽・研究・検証用の分析です。舟券購入、利益、的中を推奨または保証するものではありません。",
        "",
        "## 1. 結論",
        "",
        "- 万舟だけを抽出せず、同期間の非万舟レースを含む母集団で比較した。",
        "- 再現性評価は日付順の70/30分割で行った。検証件数が少ない条件は参考扱い。",
        "- 朝版で使える候補は、1号艇弱さ、B級人数、外枠A級、場/時間帯、勝率レンジ。",
        "- 直前版で使える候補は、1号艇展示順位、外枠展示上位、風速/波高。",
        "",
        "## 2. 使用データ",
        "",
        f"- 期間: {dates[0] if dates else ''} 〜 {dates[-1] if dates else ''}",
        f"- 対象レース数: {len(rows)}",
        f"- 除外条件: 中止、不成立、返還あり、払戻欠損は分析対象外。",
        "- 取得元: 公式B/Kダウンロードを主、OpenAPI v3が存在する場合は非公式補助として使用。",
        "- 非公式APIは正確性・完全性・リアルタイム性を保証しない。",
        "",
        "## 3. 全体ベースライン",
        "",
        f"- 全体万舟率: {format_pct(baseline)} ({manshu}/{len(rows)})",
        "",
        "### 場別",
        *summary_lines(venue_counts),
        "",
        "### レース番号別",
        *summary_lines(race_counts, 12),
        "",
        "### グレード別",
        *summary_lines(grade_counts),
        "",
        "### 時間帯別",
        *summary_lines(time_counts),
        "",
        "## 4. 万舟率が上がった単独条件",
        "",
        *markdown_table(positive_singles, 15),
        "",
        "## 5. 万舟率が上がった複合条件",
        "",
        *markdown_table(positive_compounds, 15),
        "",
        "## 6. 既存スコアとの比較",
        "",
        *top_lines,
        "",
        "- 既存スコアは `manshu_days.html` と期間が重なる場合のみ結合している。",
        "- 分析候補スコアは検証用の仮スコアで、本番ロジックには反映していない。",
        "",
        "## 7. モデル分析",
        "",
        "- 詳細は `reports/model_validation.md` を参照。",
        "- このレポートでは条件別リフトを主に見ており、モデル指標だけで結論を出していない。",
        "",
        "## 8. 実装提案",
        "",
        "### 追加候補1：1号艇危険度スコア",
        "",
        "- 根拠: `1号艇B級`, `1号艇A1でない`, `1号艇勝率低め`, `1号艇展示4位以下` の条件を層別比較。",
        "- 検証結果: 上表の該当条件と `reports/feature_lift_table.csv` を参照。",
        "- 実装案: 朝版では級別・勝率のみ、直前版では展示順位を追加加点。",
        "- 注意点: 展示順位は朝版に混ぜない。特定場・特定月偏りを継続監視する。",
        "",
        "### 追加候補2：混戦度スコア",
        "",
        "- 根拠: 勝率レンジ、B級人数、A1人数、外枠A級人数のリフトを比較。",
        "- 検証結果: `national_win_range`, `b_count`, `outer_a_count` の単独・複合条件を参照。",
        "- 実装案: 勝率レンジが小さく、外枠にA級がいる場合に段階加点。",
        "- 注意点: B/K公式DLだけでは3連率や平均STが欠けることがある。",
        "",
        "### 追加候補3：直前展示ギャップ",
        "",
        "- 根拠: `1号艇展示4位以下 × 外枠展示上位あり` を検証。",
        "- 検証結果: 複合条件表とモデル検証を参照。",
        "- 実装案: 直前版だけ `lane1_exhibition_rank4plus`, `outer_exhibition_top_flag` を加点。",
        "- 注意点: 展示タイムは締切前情報で、結果後情報ではないが朝版には使えない。",
        "",
        "## 9. 注意点",
        "",
        "- サンプル期間が短い場合、強そうな条件でも件数不足になりやすい。",
        "- 公式DL Bファイルには一部の3連率、F/L数、平均STが含まれない。",
        "- グレードはOpenAPI補助がない場合に欠損することがある。",
        "- 万舟率が高くても利益化できるとは限らない。買い目ルール未固定のROIは結論に使わない。",
        "- 結果・払戻・人気・着順・決まり手は予測特徴量に入れない。",
        "",
        "## 10. 次アクション",
        "",
        "- 高確度: 検証件数が十分で、70/30分割でも再現した条件から小さく実装検証する。",
        "- 中確度: リフトは高いが検証件数が少ない条件は、30日以上へ拡張して再確認する。",
        "- 参考: 件数30未満、特定場/日付に偏る条件はスコア本体に入れず観察枠に置く。",
        "",
        "## 件数不足だが気になる条件",
        "",
        *markdown_table(weak_but_interesting, 10),
        "",
        "## 逆に万舟率が低かった条件",
        "",
        *markdown_table(low_singles, 10),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    rows = [row for row in read_rows(Path(args.dataset)) if as_int(row.get("valid_for_analysis")) == 1]
    if not rows:
        raise SystemExit("dataset has no valid rows")
    baseline = sum(as_int(row.get("manshu_flag")) for row in rows) / len(rows)
    train, valid = time_split(rows)
    single_fields = [
        "venue_name",
        "jcd",
        "race_no",
        "grade",
        "day_label",
        "time_zone",
        "wind_speed_bucket",
        "wave_bucket",
        "lane1_class",
        "lane1_b_class",
        "lane1_national_win_bucket",
        "lane1_local_win_bucket",
        "b_count",
        "a1_count",
        "outer_a_count",
        "outer_a1_count",
        "lane1_exhibition_rank4plus",
        "outer_exhibition_top_flag",
        "early_race",
        "fixed_entry",
        "semi_final",
        "final_race",
        "selected_race",
    ]
    singles = group_conditions(rows, single_fields, baseline, args.min_count)
    add_validation_to_singles(singles, train, valid, baseline)
    compounds = compound_conditions(rows, baseline, train, valid, args.min_count)
    all_conditions = sorted(
        singles + compounds,
        key=lambda row: ((row.get("diff_vs_baseline") or 0), (row.get("lift") or 0), (row.get("n") or 0)),
        reverse=True,
    )
    write_table(Path(args.feature_lift_csv), singles)
    write_table(Path(args.patterns_csv), all_conditions)
    write_markdown(Path(args.report), rows, all_conditions, singles, compounds)
    print(f"wrote {args.report}")
    print(f"baseline={baseline:.4f} rows={len(rows)} conditions={len(all_conditions)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/analysis/race_dataset.csv")
    parser.add_argument("--min-count", type=int, default=30)
    parser.add_argument("--report", default="reports/manshu_common_patterns.md")
    parser.add_argument("--patterns-csv", default="reports/manshu_common_patterns.csv")
    parser.add_argument("--feature-lift-csv", default="reports/feature_lift_table.csv")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

