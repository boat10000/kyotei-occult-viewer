# Codex本命/準本命 3連単バックテスト

- 期間: 2024-01-01〜2026-06-29
- 朝監視: TOP10
- 買い方: 3連単のみ。2連単は除外。
- 本命: 展示後40%以上 + 12点生成
- 準本命: 展示後38〜39.9% + 1号艇危険 + 外頭2艇(5/6含む) + 内軸残り + 12点生成

```text
         segment  watch_races  buy_races  total_points  avg_points  stake_yen  payback_yen  profit_yen  roi_pct  hit_rate_pct  manshu_hit_rate_pct  over5000_hit_rate_pct  max_losing_streak  max_drawdown_yen
          本命+準本命         9108        227          2724        12.0     272400       241720      -30680    88.74         16.30                 2.64                   6.17               17.0           61220.0
        本命 40%以上          159        159          1908        12.0     190800       195560        4760   102.49         15.09                 3.77                   6.29               18.0           38800.0
準本命 38〜39.9%条件成立           68         68           816        12.0      81600        46160      -35440    56.57         19.12                 0.00                   5.88               10.0           35440.0
             見送り         8881          0             0         NaN          0            0           0      NaN           NaN                  NaN                    NaN                NaN               NaN
```