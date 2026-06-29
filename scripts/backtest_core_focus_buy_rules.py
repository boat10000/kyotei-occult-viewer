#!/usr/bin/env python3
"""Evaluate focused buy rules from the fixed core/subcore backtest ledger.

This does not rerank races.  It starts from the frozen morning-watch ledger
created by ``backtest_core_subcore_rules.py`` and only changes the tickets
inside races that already cleared the core post-exhibition condition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "postdata_manshu_backtest"


def combo_boats(value) -> list[int]:
    combo = "".join(ch for ch in str(value or "") if ch.isdigit())[:3]
    return [int(ch) for ch in combo] if len(combo) == 3 else []


def parse_tickets(value) -> set[str]:
    return {
        "".join(ch for ch in str(ticket) if ch.isdigit())[:3]
        for ticket in str(value or "").split()
        if len("".join(ch for ch in str(ticket) if ch.isdigit())[:3]) == 3
    }


def focus_tickets(row: pd.Series, rule: str) -> set[str]:
    tickets = parse_tickets(row.get("tickets"))
    heads = [int(x) for x in str(row.get("heads") or "").split(",") if str(x).strip().isdigit()]
    if not tickets or len(heads) < 2:
        return set()
    second_head = heads[1]
    filtered = set()
    for ticket in tickets:
        boats = combo_boats(ticket)
        if not boats:
            continue
        if "second_head" in rule and boats[0] != second_head:
            continue
        if "no1" in rule and 1 in boats:
            continue
        if "outer56" in rule and not ({5, 6} & set(boats)):
            continue
        filtered.add(ticket)
    return filtered


def apply_rule(rows: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = rows.copy()
    out["buy"] = 0
    out["points"] = 0
    out["stake_yen"] = 0
    out["payback_yen"] = 0
    out["hit"] = 0
    out["focused_tickets"] = ""
    core_mask = out["rule"].eq("core")
    if "round1_3" in rule:
        core_mask &= out["round"].astype(int).between(1, 3)
    if "round1_6" in rule:
        core_mask &= out["round"].astype(int).between(1, 6)
    for idx, row in out[core_mask].iterrows():
        tickets = focus_tickets(row, rule)
        if not tickets:
            continue
        trifecta = "".join(ch for ch in str(row.get("trifecta") or "") if ch.isdigit())[:3]
        hit = int(len(trifecta) == 3 and trifecta in tickets)
        out.at[idx, "buy"] = 1
        out.at[idx, "points"] = len(tickets)
        out.at[idx, "stake_yen"] = len(tickets) * 100
        out.at[idx, "payback_yen"] = int(row.get("payout_yen") or 0) if hit else 0
        out.at[idx, "hit"] = hit
        out.at[idx, "focused_tickets"] = " ".join(sorted(tickets))
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


def max_drawdown(rows: pd.DataFrame) -> int:
    equity = 0
    peak = 0
    worst = 0
    for _, row in rows.iterrows():
        equity += int(row.get("payback_yen") or 0) - int(row.get("stake_yen") or 0)
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def summarize(rows: pd.DataFrame, segment: str) -> dict:
    buy = rows[rows["buy"].eq(1)].copy()
    races = int(len(buy))
    points = int(buy["points"].sum()) if races else 0
    stake = int(buy["stake_yen"].sum()) if races else 0
    payback = int(buy["payback_yen"].sum()) if races else 0
    hits = int(buy["hit"].sum()) if races else 0
    manshu_hits = int((buy["hit"].eq(1) & buy["payout_yen"].astype(int).ge(10000)).sum()) if races else 0
    return {
        "segment": segment,
        "buy_races": races,
        "total_points": points,
        "avg_points": round(points / races, 2) if races else None,
        "stake_yen": stake,
        "payback_yen": payback,
        "profit_yen": payback - stake,
        "roi_pct": round(payback / stake * 100, 2) if stake else None,
        "hit_rate_pct": round(hits / races * 100, 2) if races else None,
        "manshu_hit_rate_pct": round(manshu_hits / races * 100, 2) if races else None,
        "max_losing_streak": max_losing_streak(buy) if races else None,
        "max_drawdown_yen": max_drawdown(buy) if races else None,
    }


def period_summary(rows: pd.DataFrame) -> pd.DataFrame:
    segments = [
        ("ALL", rows),
        ("2024H1", rows[(rows["date"] >= "2024-01-01") & (rows["date"] <= "2024-06-30")]),
        ("2024H2", rows[(rows["date"] >= "2024-07-01") & (rows["date"] <= "2024-12-31")]),
        ("2025H1", rows[(rows["date"] >= "2025-01-01") & (rows["date"] <= "2025-06-30")]),
        ("2025H2", rows[(rows["date"] >= "2025-07-01") & (rows["date"] <= "2025-12-31")]),
        ("2026H1", rows[(rows["date"] >= "2026-01-01") & (rows["date"] <= "2026-06-30")]),
    ]
    return pd.DataFrame([summarize(part, label) for label, part in segments])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument(
        "--rule",
        default="round1_3_second_head_no1_outer56",
        choices=[
            "second_head_no1_outer56",
            "round1_3_second_head_no1_outer56",
            "round1_6_second_head_no1_outer56",
        ],
    )
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    ledger = pd.read_csv(args.ledger, dtype={"trifecta": str})
    focused = apply_rule(ledger, args.rule)
    summary = period_summary(focused)
    buys = focused[focused["buy"].eq(1)].copy()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.out_prefix
    summary.to_csv(out_dir / f"{prefix}_summary.csv", index=False)
    buys.to_csv(out_dir / f"{prefix}_ledger.csv", index=False)
    payload = {
        "version": "core-focus-buy-rules-v1",
        "source_ledger": str(args.ledger),
        "rule": args.rule,
        "summary": summary.to_dict("records"),
    }
    (out_dir / f"{prefix}_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Codex本命絞り買い バックテスト",
        "",
        f"- 元台帳: `{args.ledger}`",
        f"- ルール: `{args.rule}`",
        "- 対象: 本命40%以上だけ。準本命は買わない。",
        "- 買い目: 本命12点から、外頭2番手を1着・1号艇なし・5/6絡みだけを残す。",
        "",
        "```text",
        summary.to_string(index=False),
        "```",
    ]
    (out_dir / f"{prefix}_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"wrote {out_dir / f'{prefix}_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
