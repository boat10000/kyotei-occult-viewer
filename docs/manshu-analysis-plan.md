# 万舟共通条件分析計画

調査日: 2026-06-17 JST

目的: 既存の `manshu.html` / 万舟アラートの本番ロジックを変更せず、公式ダウンロード系データを主に使って「3連単払戻金10,000円以上」の発生条件を検証する。

## 方針

- 万舟レースだけを見ず、同期間の非万舟レースを含む母集団で比較する。
- 公式サイトの画面スクレイピングは不足項目の補完に限定し、長期分析は公式B/Kダウンロードを優先する。
- rawデータは `data/raw/YYYYMMDD/`、正規化JSONは `data/normalized/YYYYMMDD.json`、分析CSVは `data/analysis/race_dataset.csv` に分ける。
- 既存公開ページ、既存HTML、既存スコアは変更しない。
- 舟券購入、利益、的中を推奨または保証する表現を追加しない。

## データリーク分離

朝版で使用可:

- 開催日、場、レース番号、レース名、締切予定時刻、日次、タイトル
- 枠番、選手名、級別、支部、年齢、体重
- 全国勝率、全国2連率、当地勝率、当地2連率
- モーター番号、モーター2連率、ボート番号、ボート2連率
- 進入固定、安定板が事前に取れる場合

直前版でのみ使用:

- 展示タイム
- 展示進入
- 展示ST
- 気象、風向、風速、波高
- チルト、部品交換、体重調整
- 3連単オッズ

予測特徴量に入れない:

- 3連単結果
- 払戻金
- 人気
- 着順
- 決まり手
- 実際のST
- 返還、F/L、欠場、中止

## 分析手順

1. 少量取得でパーサ検証
   - `python3 scripts/fetch_boatrace_data.py --date 2026-06-16 --source official --cache`
   - `python3 scripts/normalize_boatrace_data.py --date 2026-06-16`
2. 直近7日分でサンプル分析
   - `python3 scripts/fetch_boatrace_data.py --start-date 2026-06-10 --end-date 2026-06-16 --source official --cache`
   - `python3 scripts/normalize_boatrace_data.py --start-date 2026-06-10 --end-date 2026-06-16`
   - `python3 scripts/build_manshu_dataset.py --start-date 2026-06-10 --end-date 2026-06-16`
   - `python3 scripts/analyze_manshu_patterns.py --dataset data/analysis/race_dataset.csv`
   - `python3 scripts/validate_manshu_model.py --dataset data/analysis/race_dataset.csv --time-split`
3. 直近30日分へ拡張
   - 公式DLを1秒以上の間隔・キャッシュ前提で取得する。
   - 取得済み日は再取得しない。
4. 6か月〜1年分析
   - 公式DL中心。画面系取得は不足項目を指定日・指定場・指定Rに絞る。

## 出力

- `data/normalized/YYYYMMDD.json`
- `data/analysis/race_dataset.csv`
- `data/analysis/race_dataset.parquet` または `.unavailable.txt`
- `data/analysis/feature_dictionary.md`
- `reports/manshu_common_patterns.md`
- `reports/manshu_common_patterns.csv`
- `reports/feature_lift_table.csv`
- `reports/model_validation.md`
- `reports/data_quality_report.md`

## 既存スコア比較

`manshu_days.html` に既存の万舟スコア `s` が埋め込まれている期間は、`scripts/build_manshu_dataset.py` が `existing_score` として結合する。期間が一致しない場合は欠損のまま扱う。

## 注意

- 公式DLのBファイルでは、全国3連率、当地3連率、モーター3連率、ボート3連率、F/L数、平均STが欠ける場合がある。
- OpenAPI v3を補助に使う場合は、非公式、正確性保証なし、リアルタイム保証なしとして扱う。
- 件数30未満の複合条件は、リフトが高くても原則「参考」にする。
- 時系列分割を使い、同一日のデータを学習と検証に混ぜない。

