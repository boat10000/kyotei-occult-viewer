# Codex本命絞り買い バックテスト

- 元台帳: `reports/postdata_manshu_backtest/core_subcore_rules_20250101_20260629_ledger.csv`
- ルール: `second_head_no1_outer56`
- 対象: 本命40%以上だけ。準本命は買わない。
- 買い目: 本命12点から、外頭2番手を1着・1号艇なし・5/6絡みだけを残す。

```text
segment  buy_races  total_points  avg_points  stake_yen  payback_yen  profit_yen  roi_pct  hit_rate_pct  manshu_hit_rate_pct  max_losing_streak  max_drawdown_yen
    ALL         89           285        3.20      28500       115980       87480   406.95          6.74                 4.49               33.0            9700.0
 2024H1          0             0         NaN          0            0           0      NaN           NaN                  NaN                NaN               NaN
 2024H2          0             0         NaN          0            0           0      NaN           NaN                  NaN                NaN               NaN
 2025H1         25            79        3.16       7900        13340        5440   168.86          4.00                 4.00               18.0            5400.0
 2025H2         26            86        3.31       8600        80340       71740   934.19         11.54                 7.69               13.0            4200.0
 2026H1         38           120        3.16      12000        22300       10300   185.83          5.26                 2.63               20.0            5500.0
```