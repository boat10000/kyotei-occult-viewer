# Codex本命絞り買い バックテスト

- 元台帳: `reports/postdata_manshu_backtest/core_subcore_rules_20240101_20260629_ledger.csv`
- ルール: `round1_6_second_head_no1_outer56`
- 対象: 本命40%以上だけ。準本命は買わない。
- 買い目: 本命12点から、外頭2番手を1着・1号艇なし・5/6絡みだけを残す。

```text
segment  buy_races  total_points  avg_points  stake_yen  payback_yen  profit_yen  roi_pct  hit_rate_pct  manshu_hit_rate_pct  max_losing_streak  max_drawdown_yen
    ALL        117           363        3.10      36300       119070       82770   328.02          5.98                 3.42                 27              9710
 2024H1         17            54        3.18       5400            0       -5400     0.00          0.00                 0.00                 17              5400
 2024H2         21            55        2.62       5500         3090       -2410    56.18          4.76                 0.00                 15              4000
 2025H1         24            78        3.25       7800        13340        5540   171.03          4.17                 4.17                 17              5300
 2025H2         21            70        3.33       7000        80340       73340  1147.71         14.29                 9.52                 10              3200
 2026H1         34           106        3.12      10600        22300       11700   210.38          5.88                 2.94                 17              4700
```