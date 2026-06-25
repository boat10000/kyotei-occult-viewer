#!/usr/bin/env python3
"""Backtest saved manshu ranking JSONs without rerunning production ranking.

The saved daily ranking files are treated as prediction-time logs. This script
only reads production data and writes research_v2 outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from backtest_role_formations import formation_combos, parse_result, role_lanes  # noqa: E402


PLACE_ID_TO_JCD = {
    1: "01",
    2: "02",
    3: "03",
    4: "04",
    5: "05",
    6: "06",
    7: "07",
    8: "08",
    9: "09",
    10: "10",
    11: "11",
    12: "12",
    13: "13",
    14: "14",
    15: "15",
    16: "16",
    17: "17",
    18: "18",
    19: "19",
    20: "20",
    21: "21",
    22: "22",
    23: "23",
    24: "24",
}
JST = timezone(timedelta(hours=9))


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "-", "nan"):
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "nan"):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def pct(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def date_key(date_text: str) -> str:
    return str(date_text).replace("-", "")


def dashed_date(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"


def race_key(date_text: str, place_id: Any, round_no: Any) -> str:
    jcd = PLACE_ID_TO_JCD.get(as_int(place_id))
    return f"{date_text}_{jcd}_{as_int(round_no):02d}" if jcd else ""


def load_role_groups(path: Path) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            groups[row["race_id"]].append(row)
    return dict(groups)


def load_rankings(out_dir: Path, start_date: str, end_date: str) -> list[dict[str, Any]]:
    start = date_key(start_date)
    end = date_key(end_date)
    paths = sorted(out_dir.glob("boaters_manshu_ranking_*.json"))
    payloads: list[dict[str, Any]] = []
    for path in paths:
        if path.name.startswith("boaters_manshu_ranking_codex_"):
            continue
        key = path.stem.rsplit("_", 1)[-1]
        if len(key) != 8 or key < start or key > end:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        codex_path = out_dir / f"boaters_manshu_ranking_codex_{key}.json"
        if codex_path.exists():
            data["_codex_payload"] = json.loads(codex_path.read_text(encoding="utf-8"))
        payloads.append(data)
    return payloads


def result_from_ranking(row: dict[str, Any]) -> tuple[tuple[int, int, int] | None, int | None]:
    result = row.get("result") or {}
    trifecta = parse_result(result.get("trifecta"))
    payout = result.get("payout_yen")
    return trifecta, as_int(payout, -1) if payout is not None else None


def result_from_group(group: list[dict[str, Any]]) -> tuple[tuple[int, int, int] | None, int | None]:
    if not group:
        return None, None
    row = group[0]
    result = parse_result(row.get("result_trifecta"))
    payout = as_int(row.get("payout_yen"), -1)
    return result, payout if payout >= 0 else None


def selected_rows(payload: dict[str, Any], ranking_source: str) -> list[dict[str, Any]]:
    if ranking_source == "strict":
        rows = payload.get("strict_races") or []
        if rows:
            return rows
        races = payload.get("races") or []
        if races and all(str(row.get("ranking_type") or "").strip() == "strict" for row in races):
            return races
        return []
    return payload.get("races") or []


def make_event(
    payload: dict[str, Any],
    row: dict[str, Any],
    group: list[dict[str, Any]] | None,
    ranking_source: str,
    top_k: int,
    mode: str,
    formation: str,
    respect_skip: bool,
) -> dict[str, Any]:
    date_text = payload.get("date") or str(row.get("date"))
    group = group or []
    ranking_result, ranking_payout = result_from_ranking(row)
    group_result, group_payout = result_from_group(group)
    result = ranking_result or group_result
    payout = ranking_payout if ranking_payout is not None else group_payout
    skip_col = f"skip_{mode}"
    missing_reason = ""
    tickets: set[tuple[int, int, int]] = set()
    if not group:
        missing_reason = "role_dataset_missing"
    elif respect_skip and as_int(group[0].get(skip_col)):
        missing_reason = f"{skip_col}=1"
    else:
        tickets = formation_combos(role_lanes(group, mode), formation)
    points = len(tickets)
    hit = bool(result in tickets) if result and tickets else False
    net = (payout if hit and payout is not None else 0) - points * 100 if points and payout is not None else 0
    return {
        "date": date_text,
        "month": str(date_text)[:7],
        "race_id": race_key(date_text, row.get("place_id"), row.get("round")),
        "place_id": as_int(row.get("place_id")),
        "place_name": row.get("place_name"),
        "round": as_int(row.get("round")),
        "ranking_source": ranking_source,
        "top_k": top_k,
        "rank": as_int(row.get("rank")),
        "mode": mode,
        "formation": formation,
        "respect_skip": respect_skip,
        "manshu_rate_pct": as_float(row.get("manshu_rate_pct")),
        "points": points,
        "bet": bool(points and payout is not None and not missing_reason),
        "missing_reason": missing_reason,
        "result_trifecta": "-".join(map(str, result)) if result else "",
        "payout_yen": payout,
        "is_manshu_race": bool(payout is not None and payout >= 10000),
        "hit": hit,
        "hit_payout_yen": payout if hit and payout is not None else 0,
        "hit_manshu": bool(hit and payout is not None and payout >= 10000),
        "net_yen": net,
        "tickets": ["-".join(map(str, ticket)) for ticket in sorted(tickets)],
    }


def build_events(
    payloads: list[dict[str, Any]],
    role_groups: dict[str, list[dict[str, Any]]],
    top_ks: list[int],
    ranking_sources: list[str],
    modes: list[str],
    formations: list[str],
    respect_skip_values: list[bool],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for payload in payloads:
        for ranking_source in ranking_sources:
            rows = selected_rows(payload, ranking_source)
            if not rows:
                continue
            for top_k in top_ks:
                for row in rows[:top_k]:
                    key = race_key(payload.get("date"), row.get("place_id"), row.get("round"))
                    group = role_groups.get(key)
                    for mode in modes:
                        for formation in formations:
                            for respect_skip in respect_skip_values:
                                events.append(
                                    make_event(payload, row, group, ranking_source, top_k, mode, formation, respect_skip)
                                )
    return events


def max_losing_streak(events: list[dict[str, Any]]) -> int:
    current = best = 0
    for event in sorted(events, key=lambda row: (row["date"], row["place_id"], row["round"])):
        if not event["bet"]:
            continue
        if event["hit"]:
            current = 0
        else:
            current += 1
            best = max(best, current)
    return best


def max_drawdown(events: list[dict[str, Any]]) -> int:
    equity = peak = 0
    worst = 0
    for event in sorted(events, key=lambda row: (row["date"], row["place_id"], row["round"])):
        if not event["bet"]:
            continue
        equity += as_int(event.get("net_yen"))
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return int(abs(worst))


def summarize(events: list[dict[str, Any]], label: dict[str, Any]) -> dict[str, Any]:
    selected = len(events)
    bought = [event for event in events if event["bet"]]
    settled = [event for event in events if event.get("payout_yen") is not None]
    hits = [event for event in bought if event["hit"]]
    manshu_hits = [event for event in bought if event["hit_manshu"]]
    selected_manshu = [event for event in settled if event["is_manshu_race"]]
    points = sum(as_int(event["points"]) for event in bought)
    cost = points * 100
    gross = sum(as_int(event["hit_payout_yen"]) for event in hits)
    hit_payouts = [as_int(event["hit_payout_yen"]) for event in hits]
    max_hit = max(hit_payouts) if hit_payouts else 0
    gross_without_max = gross - max_hit if max_hit else gross
    return {
        **label,
        "target_races": selected,
        "settled_races": len(settled),
        "bought_races": len(bought),
        "skipped_races": selected - len(bought),
        "total_points": points,
        "purchase_yen": cost,
        "return_yen": gross,
        "profit_yen": gross - cost,
        "roi_pct": pct(gross, cost),
        "roi_without_max_hit_pct": pct(gross_without_max, cost),
        "hit_count": len(hits),
        "hit_rate_pct": pct(len(hits), len(bought)),
        "manshu_hit_count": len(manshu_hits),
        "manshu_hit_rate_pct": pct(len(manshu_hits), len(bought)),
        "selected_manshu_races": len(selected_manshu),
        "manshu_capture_rate_pct": pct(len(manshu_hits), len(selected_manshu)),
        "avg_hit_payout_yen": round(statistics.mean(hit_payouts), 2) if hit_payouts else None,
        "median_hit_payout_yen": round(statistics.median(hit_payouts), 2) if hit_payouts else None,
        "max_hit_payout_yen": max_hit or None,
        "max_losing_streak": max_losing_streak(events),
        "max_drawdown_yen": max_drawdown(events),
        "sample_dates": len({event["date"] for event in events}),
    }


def bootstrap_roi(events: list[dict[str, Any]], iterations: int = 300, seed: int = 20260625) -> tuple[float | None, float | None]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["bet"]:
            by_date[event["date"]].append(event)
    dates = sorted(by_date)
    if len(dates) < 2:
        return None, None
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(iterations):
        sample_dates = [rng.choice(dates) for _i in dates]
        sample_events = [event for date in sample_dates for event in by_date[date]]
        points = sum(as_int(event["points"]) for event in sample_events)
        cost = points * 100
        gross = sum(as_int(event["hit_payout_yen"]) for event in sample_events if event["hit"])
        if cost:
            values.append(gross / cost * 100)
    if not values:
        return None, None
    values.sort()
    lo = values[int(len(values) * 0.025)]
    hi = values[min(len(values) - 1, int(len(values) * 0.975))]
    return round(lo, 2), round(hi, 2)


def aggregate(events: list[dict[str, Any]], group_cols: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[tuple(event.get(col) for col in group_cols)].append(event)
    rows: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        label = {col: value for col, value in zip(group_cols, key)}
        row = summarize(items, label)
        if group_cols == ["ranking_source", "top_k", "mode", "formation", "respect_skip"]:
            lo, hi = bootstrap_roi(items)
            row["roi_ci95_low_pct"] = lo
            row["roi_ci95_high_pct"] = hi
        rows.append(row)
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


def write_report(path: Path, summary_rows: list[dict[str, Any]], month_rows: list[dict[str, Any]], venue_rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = [
        row
        for row in summary_rows
        if row["ranking_source"] == "strict"
        and as_int(row["top_k"]) == 10
        and row["mode"] == "preview"
        and row["formation"] == "B"
        and str(row["respect_skip"]) == "False"
    ]
    focus_row = focus[0] if focus else {}
    mode_pairs = {
        row["mode"]: row
        for row in summary_rows
        if row["ranking_source"] == "strict"
        and as_int(row["top_k"]) == 10
        and row["formation"] == "B"
        and str(row["respect_skip"]) == "False"
    }
    def line(row: dict[str, Any]) -> str:
        return (
            f"{row.get('return_yen', 0):,}円 / {row.get('purchase_yen', 0):,}円 = "
            f"{row.get('roi_pct')}%（的中 {row.get('hit_count')}/{row.get('bought_races')}、"
            f"万舟 {row.get('manshu_hit_count')}）"
        )

    top_rows = sorted(summary_rows, key=lambda row: (as_float(row.get("roi_pct")) or -1, as_int(row.get("bought_races"))), reverse=True)[:12]
    table = ["| 順位系統 | TOP | モード | 形 | skip除外 | 購入R | 点数 | 回収率 | 収支 | 的中率 | 万舟率 | 最大連敗 | DD | CI95 |",
             "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in top_rows:
        table.append(
            "| {ranking_source} | {top_k} | {mode} | {formation} | {respect_skip} | {bought_races} | {total_points} | {roi_pct} | {profit_yen} | {hit_rate_pct} | {manshu_hit_rate_pct} | {max_losing_streak} | {max_drawdown_yen} | {lo}-{hi} |".format(
                **row,
                lo=row.get("roi_ci95_low_pct"),
                hi=row.get("roi_ci95_high_pct"),
            )
        )
    month_focus = [
        row for row in month_rows
        if row.get("ranking_source") == "strict" and row.get("mode") == "preview" and row.get("formation") == "B" and as_int(row.get("top_k")) == 10 and str(row.get("respect_skip")) == "False"
    ]
    month_table = ["| 月 | 購入R | 回収率 | 収支 | 万舟的中 | 最大配当 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in month_focus:
        month_table.append(f"| {row.get('month')} | {row.get('bought_races')} | {row.get('roi_pct')} | {row.get('profit_yen')} | {row.get('manshu_hit_count')} | {row.get('max_hit_payout_yen')} |")
    venue_focus = [
        row for row in venue_rows
        if row.get("ranking_source") == "strict" and row.get("mode") == "preview" and row.get("formation") == "B" and as_int(row.get("top_k")) == 10 and str(row.get("respect_skip")) == "False"
    ]
    venue_focus = sorted(venue_focus, key=lambda row: as_int(row.get("bought_races")), reverse=True)[:20]
    venue_table = ["| 会場 | 購入R | 回収率 | 収支 | 万舟的中 | 最大配当 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in venue_focus:
        venue_table.append(f"| {row.get('place_name')} | {row.get('bought_races')} | {row.get('roi_pct')} | {row.get('profit_yen')} | {row.get('manshu_hit_count')} | {row.get('max_hit_payout_yen')} |")
    text = [
        "# research_v2 Backtest ROI",
        "",
        "保存済み日別ランキングJSONを予測時点ログとして使用し、過去結果を見てランキングを再実行していません。",
        "舟券購入を推奨するものではなく、100円均等購入の検証です。",
        "",
        "## 対象と欠損",
        "",
        f"- 生成時刻: {meta['generated_at']}",
        f"- 期間: {meta['start_date']} - {meta['end_date']}",
        f"- 保存済みランキング日数: {meta['ranking_days']}",
        f"- role dataset対象日: {meta['role_date_min']} - {meta['role_date_max']}",
        f"- role dataset欠損イベント: {meta['missing_reason_counts'].get('role_dataset_missing', 0)}",
        "",
        "## 主対象: 厳選TOP10・直前版・18点フォーメーションB",
        "",
        line(focus_row) if focus_row else "- 該当なし",
        "",
        "- 計算式: 払戻総額 ÷ 購入総額 × 100",
        "- 払戻総額には万舟以外の的中も含めています。",
        "- `roi_without_max_hit_pct` で最高配当1件を除いた依存度も確認しています。",
        "- 返還・中止・結果欠損・role dataset欠損は購入対象外として明示スキップしています。",
        "",
        "## 朝版と直前版の差（厳選TOP10・B・skip除外なし）",
        "",
        f"- morning: {line(mode_pairs.get('morning', {})) if 'morning' in mode_pairs else 'なし'}",
        f"- preview: {line(mode_pairs.get('preview', {})) if 'preview' in mode_pairs else 'なし'}",
        "",
        "## 上位集計",
        "",
        "\n".join(table),
        "",
        "## 月別（主対象）",
        "",
        "\n".join(month_table),
        "",
        "## 会場別（主対象、購入数順TOP20）",
        "",
        "\n".join(venue_table),
        "",
        "## 判定",
        "",
        "- このPhaseでは候補モデルを採用しません。現行保存ログの正確な会計基盤を作った段階です。",
        "- 回収率100%以上が出ても、独立最終期間・信頼区間・高配当依存を見ずに採用しません。",
    ]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2026-05-01")
    parser.add_argument("--end-date", default="2026-06-25")
    parser.add_argument("--ranking-dir", default="data/output")
    parser.add_argument("--role-dataset", default="data/analysis/boat_role_dataset.csv")
    parser.add_argument("--out-dir", default="data/output/research_v2")
    parser.add_argument("--report-dir", default="reports/research_v2")
    args = parser.parse_args()

    payloads = load_rankings(ROOT / args.ranking_dir, args.start_date, args.end_date)
    role_groups = load_role_groups(ROOT / args.role_dataset)
    role_dates = [group[0]["date"] for group in role_groups.values() if group]
    events = build_events(
        payloads,
        role_groups,
        top_ks=[1, 3, 5, 10],
        ranking_sources=["strict", "all"],
        modes=["morning", "preview"],
        formations=["A", "B", "C", "D"],
        respect_skip_values=[False, True],
    )
    summary_rows = aggregate(events, ["ranking_source", "top_k", "mode", "formation", "respect_skip"])
    month_rows = aggregate(events, ["ranking_source", "top_k", "mode", "formation", "respect_skip", "month"])
    venue_rows = aggregate(events, ["ranking_source", "top_k", "mode", "formation", "respect_skip", "place_name"])
    out_dir = ROOT / args.out_dir
    report_dir = ROOT / args.report_dir
    write_csv(report_dir / "backtest_roi_summary.csv", summary_rows)
    write_csv(report_dir / "backtest_roi_by_month.csv", month_rows)
    write_csv(report_dir / "backtest_roi_by_venue.csv", venue_rows)
    meta = {
        "version": "research-v2-backtest-1",
        "generated_at": now_iso(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "ranking_days": len(payloads),
        "role_dataset": args.role_dataset,
        "role_date_min": min(role_dates) if role_dates else None,
        "role_date_max": max(role_dates) if role_dates else None,
        "missing_reason_counts": dict(Counter(event["missing_reason"] for event in events if event["missing_reason"])),
        "event_count": len(events),
        "summary_rows": summary_rows,
        "accounting": {
            "stake_per_ticket_yen": 100,
            "purchase_yen": "points * 100",
            "return_yen": "sum of all hit payouts, including non-manshu hits",
            "refund_rule": "no bet when result/payout missing, canceled, or role dataset missing",
        },
        "outputs": {
            "summary_csv": "reports/research_v2/backtest_roi_summary.csv",
            "month_csv": "reports/research_v2/backtest_roi_by_month.csv",
            "venue_csv": "reports/research_v2/backtest_roi_by_venue.csv",
            "report_md": "reports/research_v2/backtest_roi.md",
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "backtest_summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_report(report_dir / "backtest_roi.md", summary_rows, month_rows, venue_rows, meta)
    print(json.dumps({"events": len(events), "ranking_days": len(payloads), "summary_rows": len(summary_rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
