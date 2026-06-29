# Codex本命絞り買い バックテスト

- 元台帳: `reports/postdata_manshu_backtest/core_subcore_rules_20250101_20260629_ledger.csv`
- ルール: `round1_3_second_head_no1_outer56`
- 対象: 本命40%以上だけ。準本命は買わない。
- 買い目: 本命12点から、外頭2番手を1着・1号艇なし・5/6絡みだけを残す。

```text
segment  buy_races  total_points  avg_points  stake_yen  payback_yen  profit_yen  roi_pct  hit_rate_pct  manshu_hit_rate_pct  max_losing_streak  max_drawdown_yen
    ALL         69           228        3.30      22800       115980       93180   508.68          8.70                 5.80               24.0            7100.0
 2024H1          0             0         NaN          0            0           0      NaN           NaN                  NaN                NaN               NaN
 2024H2          0             0         NaN          0            0           0      NaN           NaN                  NaN                NaN               NaN
 2025H1         21            70        3.33       7000        13340        6340   190.57          4.76                 4.76               14.0            4500.0
 2025H2         19            65        3.42       6500        80340       73840  1236.00         15.79                10.53                9.0            3000.0
 2026H1         29            93        3.21       9300        22300       13000   239.78          6.90                 3.45               15.0            4100.0
```