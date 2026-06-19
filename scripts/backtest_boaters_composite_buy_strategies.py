#!/usr/bin/env python3
"""Backtest 10-15 point trifecta formations for BOATERS composite manshu edges."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from search_boaters_manshu_composite_conditions import (  # noqa: E402
    DEFAULT_DB,
    build_atoms,
    build_race_frame,
    load_boats,
)


DEFAULT_CONDITIONS = ROOT / "data" / "output" / "manshu_composite_condition_search" / "all_composite_conditions.csv"
OUT_DIR = ROOT / "data" / "output" / "composite_buy_strategy_search"


def as_int(value, default=0):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        output = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(output) else output


def pct(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value) * 100, 2)


def parse_trifecta(value):
    digits = [int(ch) for ch in str(value or "") if ch.isdigit()]
    return tuple(digits[:3]) if len(digits) >= 3 else None


def unique(seq):
    out = []
    for item in seq:
        item = as_int(item)
        if 1 <= item <= 6 and item not in out:
            out.append(item)
    return out


def col(row, boat, name):
    return as_float(row.get(f"b{boat}_{name}"))


def boat_score(row, boat, mode):
    ai_pred = col(row, boat, "ai_prediction_pct") or 0
    ai_plus = col(row, boat, "ai_plus") or 0
    ai_rank = col(row, boat, "ai_plus_rank") or 6
    avgdiff = col(row, boat, "avg_isshu_diff")
    avgdiff = -0.5 if avgdiff is None else avgdiff
    tenji = col(row, boat, "tenji_rank_use") or 6
    isshu = col(row, boat, "isshu_rank") or 6
    st_rank = col(row, boat, "st_rank_general") or 6
    if mode == "ai_pred":
        return ai_pred
    if mode == "ai_plus":
        return ai_plus
    if mode == "exhibit":
        return avgdiff * 55 + (7 - tenji) * 6 + (7 - isshu) * 4 + ai_pred * 0.25
    if mode == "underdog":
        return ai_rank * 10 + avgdiff * 50 + (7 - tenji) * 5 + ai_pred * 0.2
    if mode == "st_exhibit":
        return (7 - st_rank) * 8 + avgdiff * 40 + (7 - tenji) * 5 + ai_pred * 0.2
    if mode == "worst":
        return -(ai_plus * 0.45 + ai_pred * 0.35 + avgdiff * 40 + (7 - tenji) * 4)
    return 0


def top_by(row, boats, mode, n):
    return unique(
        boat
        for boat, _score in sorted(
            [(boat, boat_score(row, boat, mode)) for boat in boats],
            key=lambda item: item[1],
            reverse=True,
        )[:n]
    )


def rank_boat(row, rank):
    return as_int(row.get(f"ai_rank{rank}_boat"))


def head_candidates(row, name):
    if name == "ai_pred_non1":
        return top_by(row, [2, 3, 4, 5, 6], "ai_pred", 2)
    if name == "ai_plus_non1":
        return top_by(row, [2, 3, 4, 5, 6], "ai_plus", 2)
    if name == "exhibit_non1":
        return top_by(row, [2, 3, 4, 5, 6], "exhibit", 2)
    if name == "underdog_exhibit":
        ranked = [rank_boat(row, r) for r in [4, 5, 6]]
        return unique(top_by(row, unique(ranked + [2, 3, 4, 5, 6]), "underdog", 2))
    if name == "rank5_rank6":
        return unique([rank_boat(row, 5), rank_boat(row, 6)] + top_by(row, [2, 3, 4, 5, 6], "exhibit", 2))[:2]
    if name == "outer_value":
        return top_by(row, [3, 4, 5, 6], "exhibit", 2)
    if name == "st_mid_outer":
        return top_by(row, [3, 4, 5, 6], "st_exhibit", 2)
    fixed = {
        "fixed_23": [2, 3],
        "fixed_34": [3, 4],
        "fixed_45": [4, 5],
        "fixed_56": [5, 6],
        "fixed_24": [2, 4],
        "fixed_35": [3, 5],
        "fixed_25": [2, 5],
        "fixed_46": [4, 6],
    }
    return fixed.get(name, [])


def pool_candidates(row, name, kill=None):
    kill = set(kill or [])
    if name == "axis_ai_plus_top2":
        pool = [rank_boat(row, 1), rank_boat(row, 2)]
    elif name == "axis_ai_plus_top3":
        pool = [rank_boat(row, 1), rank_boat(row, 2), rank_boat(row, 3)]
    elif name == "axis_ai_pred_top2":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "ai_pred", 2)
    elif name == "axis_ai_pred_top3":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "ai_pred", 3)
    elif name == "axis_exhibit_top2":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "exhibit", 2)
    elif name == "axis_exhibit_top3":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "exhibit", 3)
    elif name == "axis_1_best_non1":
        pool = [1] + top_by(row, [2, 3, 4, 5, 6], "ai_pred", 1)
    elif name == "support_best4_exhibit":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "exhibit", 4)
    elif name == "support_best5_exhibit":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "exhibit", 5)
    elif name == "support_best4_ai":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "ai_pred", 4)
    elif name == "support_best5_ai":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "ai_pred", 5)
    elif name == "support_outer_plus_ai":
        pool = [5, 6] + top_by(row, [1, 2, 3, 4], "ai_pred", 3)
    elif name == "support_underdog_mix":
        pool = top_by(row, [1, 2, 3, 4, 5, 6], "underdog", 5)
    else:
        pool = [1, 2, 3, 4, 5, 6]
    return [boat for boat in unique(pool) if boat not in kill]


def kill_candidate(row, name):
    if name == "kill_1":
        return [1]
    if name == "kill_rank6":
        return unique([rank_boat(row, 6)])
    if name == "kill_worst_ai_plus":
        return top_by(row, [1, 2, 3, 4, 5, 6], "worst", 1)
    if name == "kill_worst_exhibit":
        return top_by(row, [1, 2, 3, 4, 5, 6], "worst", 1)
    if name == "kill_6":
        return [6]
    return []


def make_tickets(row, strategy):
    kill = kill_candidate(row, strategy["kill"])
    heads = [boat for boat in head_candidates(row, strategy["head"]) if boat not in kill]
    second = pool_candidates(row, strategy["second"], kill)
    third = pool_candidates(row, strategy["third"], kill)
    if strategy["template"] == "swap23":
        second, third = third, second
    if len(heads) != 2:
        return set(), heads, second, third, kill
    tickets = set()
    for a, b, c in itertools.product(heads, second, third):
        if len({a, b, c}) == 3:
            tickets.add((a, b, c))
    return tickets, heads, second, third, kill


def eval_rows(records, idxs, strategy, min_payout=5000):
    n = len(idxs)
    bets = hits = manshu_hits = plus50_hits = 0
    cost = gross = gross_50 = gross_manshu = 0
    points_list = []
    examples = []
    for idx in idxs:
        row = records[int(idx)]
        tickets, heads, second, third, kill = make_tickets(row, strategy)
        points = len(tickets)
        if points < 10 or points > 15:
            continue
        result = parse_trifecta(row.get("trifecta"))
        payout = as_int(row.get("payout"))
        if not result:
            continue
        bets += 1
        points_list.append(points)
        cost += points * 100
        hit = result in tickets
        if hit:
            hits += 1
            gross += payout
            if payout >= min_payout:
                plus50_hits += 1
                gross_50 += payout
            if payout >= 10000:
                manshu_hits += 1
                gross_manshu += payout
                if len(examples) < 5:
                    examples.append(
                        {
                            "date": str(row.get("date"))[:10],
                            "place_name": row.get("place_name"),
                            "round": as_int(row.get("round")),
                            "trifecta": "-".join(map(str, result)),
                            "payout_yen": payout,
                            "tickets": ["-".join(map(str, t)) for t in sorted(tickets)],
                            "heads": heads,
                            "second": second,
                            "third": third,
                            "kill": kill,
                        }
                    )
    return {
        "bet_races": bets,
        "avg_points": round(float(np.mean(points_list)), 2) if points_list else None,
        "cost_yen": cost,
        "hit_count": hits,
        "hit_rate_pct": pct(hits / bets) if bets else None,
        "plus50_hit_count": plus50_hits,
        "plus50_hit_rate_pct": pct(plus50_hits / bets) if bets else None,
        "manshu_hit_count": manshu_hits,
        "manshu_hit_rate_pct": pct(manshu_hits / bets) if bets else None,
        "roi_all_pct": pct(gross / cost) if cost else None,
        "roi_50plus_pct": pct(gross_50 / cost) if cost else None,
        "roi_manshu_only_pct": pct(gross_manshu / cost) if cost else None,
        "return_yen": gross,
        "return_50plus_yen": gross_50,
        "return_manshu_yen": gross_manshu,
        "examples": examples,
    }


def load_conditions(path, top_n):
    df = pd.read_csv(path)
    df = df[df["condition_count"].isin([3, 5, 7])].copy()
    df = df.sort_values(["score", "manshu_rate_pct", "races"], ascending=False)
    return df.head(top_n).to_dict("records")


def mask_for_condition(atoms_by_id, atom_ids):
    masks = []
    for atom_id in str(atom_ids).split(","):
        atom = atoms_by_id.get(atom_id)
        if atom is None:
            return None
        masks.append(atom["mask"])
    return np.logical_and.reduce(masks) if masks else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--conditions", default=str(DEFAULT_CONDITIONS))
    parser.add_argument("--condition-top-n", type=int, default=160)
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--min-train-races", type=int, default=35)
    parser.add_argument("--min-valid-races", type=int, default=18)
    parser.add_argument("--min-valid-manshu-hits", type=int, default=2)
    args = parser.parse_args()

    boats = load_boats(Path(args.db), "2020-01-01")
    race = build_race_frame(boats).reset_index(drop=True)
    race["date"] = pd.to_datetime(race["date"])
    records = race.to_dict("records")
    atoms_by_id = {item["id"]: item for item in build_atoms(race)}
    conditions = load_conditions(Path(args.conditions), args.condition_top_n)

    train_mask = race["date"].lt(pd.Timestamp("2025-01-01")).to_numpy()
    valid_mask = race["date"].ge(pd.Timestamp("2025-01-01")).to_numpy()

    head_names = [
        "ai_pred_non1",
        "exhibit_non1",
        "underdog_exhibit",
        "rank5_rank6",
        "outer_value",
        "st_mid_outer",
    ]
    second_names = [
        "axis_ai_plus_top2",
        "axis_ai_pred_top2",
        "axis_exhibit_top2",
        "axis_1_best_non1",
    ]
    third_names = [
        "support_best4_exhibit",
        "support_best5_exhibit",
        "support_best4_ai",
        "support_outer_plus_ai",
    ]
    kills = ["kill_1", "kill_rank6", "kill_worst_ai_plus"]
    templates = ["normal", "swap23"]

    rows = []
    total = 0
    for cond in conditions:
        mask = mask_for_condition(atoms_by_id, cond["atom_ids"])
        if mask is None:
            continue
        train_idxs = np.flatnonzero(mask & train_mask)
        valid_idxs = np.flatnonzero(mask & valid_mask)
        if len(train_idxs) < args.min_train_races or len(valid_idxs) < args.min_valid_races:
            continue
        for head, second, third, kill, template in itertools.product(head_names, second_names, third_names, kills, templates):
            total += 1
            strategy = {"head": head, "second": second, "third": third, "kill": kill, "template": template}
            valid = eval_rows(records, valid_idxs, strategy)
            if valid["bet_races"] < args.min_valid_races:
                continue
            if (valid["manshu_hit_count"] or 0) < args.min_valid_manshu_hits:
                continue
            if (valid["roi_manshu_only_pct"] or 0) < 100:
                continue
            train = eval_rows(records, train_idxs, strategy)
            if train["bet_races"] < args.min_train_races:
                continue
            if (train["roi_manshu_only_pct"] or 0) < 45 and (train["roi_50plus_pct"] or 0) < 55:
                continue
            row = {
                "condition": cond["condition"],
                "condition_atom_ids": cond["atom_ids"],
                "condition_manshu_rate_pct": cond["manshu_rate_pct"],
                "condition_recent_manshu_rate_pct": cond.get("recent_manshu_rate_pct"),
                "head_selector": head,
                "second_selector": second,
                "third_selector": third,
                "kill_selector": kill,
                "template": template,
                "train_bet_races": train["bet_races"],
                "train_avg_points": train["avg_points"],
                "train_manshu_hit_count": train["manshu_hit_count"],
                "train_manshu_hit_rate_pct": train["manshu_hit_rate_pct"],
                "train_roi_all_pct": train["roi_all_pct"],
                "train_roi_50plus_pct": train["roi_50plus_pct"],
                "train_roi_manshu_only_pct": train["roi_manshu_only_pct"],
                "valid_bet_races": valid["bet_races"],
                "valid_avg_points": valid["avg_points"],
                "valid_manshu_hit_count": valid["manshu_hit_count"],
                "valid_manshu_hit_rate_pct": valid["manshu_hit_rate_pct"],
                "valid_plus50_hit_count": valid["plus50_hit_count"],
                "valid_roi_all_pct": valid["roi_all_pct"],
                "valid_roi_50plus_pct": valid["roi_50plus_pct"],
                "valid_roi_manshu_only_pct": valid["roi_manshu_only_pct"],
                "valid_examples": valid["examples"],
                "strategy": strategy,
            }
            row["stability_score"] = round(
                min(row["valid_roi_manshu_only_pct"] or 0, row["train_roi_manshu_only_pct"] or 0)
                + (row["valid_manshu_hit_rate_pct"] or 0) * 1.8
                + math.log10(row["valid_bet_races"] + 1) * 8,
                4,
            )
            rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            ["valid_roi_manshu_only_pct", "valid_manshu_hit_rate_pct", "valid_bet_races", "stability_score"],
            ascending=False,
        ).reset_index(drop=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "composite_buy_strategy_candidates.csv"
    json_path = out_dir / "composite_buy_strategy_summary.json"
    if out.empty:
        csv_path.write_text("", encoding="utf-8")
        selected = []
    else:
        csv_out = out.drop(columns=["valid_examples", "strategy"]).copy()
        csv_out.to_csv(csv_path, index=False, encoding="utf-8-sig")
        selected = out.head(20).to_dict("records")

    summary = {
        "version": "composite-buy-strategy-v1",
        "db": str(Path(args.db)),
        "conditions_source": str(Path(args.conditions)),
        "evaluated_strategy_variants": total,
        "candidate_count": int(len(out)),
        "train_period": "2020-01-01 to 2024-12-31",
        "validation_period": "2025-01-01 to 2026-06-18",
        "filters": {
            "points": "10 to 15",
            "return_focus": "manshu_only and 50x_plus proxy",
            "min_train_races": args.min_train_races,
            "min_valid_races": args.min_valid_races,
            "min_valid_manshu_hits": args.min_valid_manshu_hits,
        },
        "top_candidates": selected,
        "outputs": {"csv": str(csv_path), "json": str(json_path)},
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
