# Feature Dictionary

予測に使う場合は、結果後にしか分からない列を除外する。

- `manshu_flag`: 目的変数。3連単払戻金が10,000円以上なら1。
- `big_manshu_flag`: 目的変数。3連単払戻金が50,000円以上なら1。
- `valid_for_analysis`: 中止、不成立、返還あり、払戻欠損を除いた分析対象フラグ。
- `time_zone`: 締切時刻から morning/day/evening/night/midnight に分類。
- `early_race`: 1R〜4Rなら1。
- `semi_final`: レース名に準優を含む。
- `final_race`: レース名に優勝を含む。
- `selected_race`: レース名に選抜、特選、特賞、ドリーム等を含む。
- `lane1_*`: 1号艇危険度を測るための1号艇特徴量。
- `a1_count/a2_count/b_count`: 6艇の級別構成。
- `outer_*`: 4〜6号艇の実力・展示・モーターに関する特徴量。
- `national_win_range/local_win_range`: 6艇の勝率レンジ。小さいほど混戦の代理指標。
- `exhibition_time_range`: 展示タイム最大-最小。直前版特徴量。
- `existing_score`: 既存 manshu_days.html にスコアがある期間のみ結合。

## データリーク注意

- 朝版で使える: 出走表、開催、番組、選手、モーター/ボートの事前情報。
- 直前版で使える: 展示タイム、展示進入、展示ST、気象、オッズ。
- 予測に使わない: `payout_yen`, `manshu_flag`, `result_trifecta`, `popularity`, `decision`, 実際の着順。
