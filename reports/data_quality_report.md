# Manshu Data Quality Report

このレポートは分析用データセット生成時点の品質確認であり、舟券購入を推奨するものではありません。

- 取得日数: 7 / 7
- レース数: 1008
- 分析対象レース数: 987
- 6艇情報あり: 1008
- 万舟数: 161
- 全体万舟率: 16.31%
- 既存スコア結合数: 863
- Parquet出力: wrote data/analysis/race_dataset.parquet

## 欠損数

- `lane1_class`: 0 (0.0%)
- `lane1_national_win_rate`: 0 (0.0%)
- `lane1_local_win_rate`: 0 (0.0%)
- `lane1_motor_quinella_rate`: 0 (0.0%)
- `lane1_exhibition_time`: 3 (0.3%)
- `wind_speed_m`: 1 (0.1%)
- `wave_cm`: 1 (0.1%)
- `grade`: 0 (0.0%)
- `existing_score`: 145 (14.4%)

## 注意

- 公式DLのBファイルには3連率、F/L数、平均STが含まれない場合がある。
- グレード、開催タイトル、日次はOpenAPI v3 programsがある場合のみ非公式補助で補完される。
- 展示タイム・展示STは直前版特徴量として扱う。
- `popularity`, `decision`, `result_trifecta`, `payout_yen` はラベル・検証専用。
- `existing_score` は `manshu_days.html` と期間が重なる場合のみ結合される。
