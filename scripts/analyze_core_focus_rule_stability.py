#!/usr/bin/env python3
"""Create stability diagnostics for the Codex core-focus buy rule."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "postdata_manshu_backtest"


def summarize(rows: pd.DataFrame, segment: str) -> dict:
    stake = int(rows["stake_yen"].sum()) if not rows.empty else 0
    payback = int(rows["payback_yen"].sum()) if not rows.empty else 0
    hits = int(rows["hit"].sum()) if not rows.empty else 0
    manshu_hits = int((rows["hit"].eq(1) & rows["payout_yen"].astype(int).ge(10000)).sum()) if not rows.empty else 0
    return {
        "segment": segment,
        "buy_races": int(len(rows)),
        "total_points": int(rows["points"].sum()) if not rows.empty else 0,
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": round(payback / stake * 100, 2) if stake else None,
        "hit_rate_pct": round(hits / len(rows) * 100, 2) if len(rows) else None,
        "manshu_hit_rate_pct": round(manshu_hits / len(rows) * 100, 2) if len(rows) else None,
    }


def payout_dependency(rows: pd.DataFrame) -> list[dict]:
    hits = rows[rows["payback_yen"].astype(int).gt(0)].copy()
    hits = hits.sort_values("payback_yen", ascending=False)
    total_stake = int(rows["stake_yen"].sum())
    total_payback = int(rows["payback_yen"].sum())
    out = [
        {
            "scenario": "all_hits",
            "removed_hits": 0,
            "payback_yen": total_payback,
            "roi_pct": round(total_payback / total_stake * 100, 2) if total_stake else None,
        }
    ]
    for n in range(1, min(5, len(hits)) + 1):
        removed = int(hits.head(n)["payback_yen"].sum())
        payback = total_payback - removed
        out.append(
            {
                "scenario": f"without_top_{n}_hit",
                "removed_hits": n,
                "removed_payback_yen": removed,
                "payback_yen": payback,
                "roi_pct": round(payback / total_stake * 100, 2) if total_stake else None,
            }
        )
    return out


def max_losing_streak(rows: pd.DataFrame) -> int:
    streak = 0
    worst = 0
    for hit in rows["hit"].fillna(0).astype(int):
        if hit:
            streak = 0
        else:
            streak += 1
            worst = max(worst, streak)
    return worst


def stability_decision(summary: dict, dependency: list[dict]) -> str:
    roi = summary.get("roi_pct") or 0
    without_top_2 = next((row.get("roi_pct") for row in dependency if row.get("scenario") == "without_top_2_hit"), None)
    losing = summary.get("max_losing_streak") or 0
    if roi >= 180 and without_top_2 and without_top_2 >= 100 and losing <= 30:
        return "FORWARD_TEST_OK"
    if roi >= 100:
        return "FORWARD_TEST_WITH_CAUTION"
    return "REJECT_OR_RESEARCH_ONLY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(args.ledger)
    rows["date"] = rows["date"].astype(str)
    rows["month"] = rows["date"].str.slice(0, 7)

    overall = summarize(rows, "ALL")
    overall["avg_points"] = round(rows["points"].sum() / len(rows), 2) if len(rows) else None
    overall["max_losing_streak"] = max_losing_streak(rows)
    dependency = payout_dependency(rows)
    overall["decision"] = stability_decision(overall, dependency)

    by_month = pd.DataFrame([summarize(group, month) for month, group in rows.groupby("month")])
    by_venue = pd.DataFrame([summarize(group, venue) for venue, group in rows.groupby("place_name")])
    by_venue = by_venue.sort_values(["buy_races", "roi_pct"], ascending=[False, False])
    hits = rows[rows["hit"].eq(1)].sort_values("payback_yen", ascending=False)

    prefix = args.out_prefix
    by_month.to_csv(out_dir / f"{prefix}_by_month.csv", index=False)
    by_venue.to_csv(out_dir / f"{prefix}_by_venue.csv", index=False)
    hits.to_csv(out_dir / f"{prefix}_hits.csv", index=False)
    payload = {
        "version": "core-focus-stability-v1",
        "source_ledger": str(args.ledger),
        "overall": overall,
        "payout_dependency": dependency,
        "top_hits": hits.head(10).to_dict("records"),
    }
    (out_dir / f"{prefix}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Codex本命絞り 安定性診断",
        "",
        f"- 元台帳: `{args.ledger}`",
        f"- 判定: `{overall['decision']}`",
        "",
        "## 全体",
        "",
        "```text",
        pd.DataFrame([overall]).to_string(index=False),
        "```",
        "",
        "## 大当たり依存",
        "",
        "```text",
        pd.DataFrame(dependency).to_string(index=False),
        "```",
        "",
        "## 的中一覧",
        "",
        "```text",
        hits[["date", "place_name", "round", "payout_yen", "trifecta", "focused_tickets"]].to_string(index=False),
        "```",
        "",
        "## 注意",
        "",
        "- 回収率は強いが、的中率は低く最大連敗が長い。",
        "- 本命絞りは少点数の高配当狙い。連敗前提の前向き検証ルールとして扱う。",
        "- 大当たり上位2本を抜いても100%を超えるかを継続監視する。",
    ]
    (out_dir / f"{prefix}.md").write_text("\n".join(lines), encoding="utf-8")
    print(pd.DataFrame([overall]).to_string(index=False))
    print(pd.DataFrame(dependency).to_string(index=False))
    print(f"wrote {out_dir / f'{prefix}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
