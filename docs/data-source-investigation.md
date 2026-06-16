# ボートレースデータ取得元調査

調査日: 2026-06-16 JST  
追記: 2026-06-17 JST

対象: 既存の `manshu.html` / `kyotei-occult-viewer` を改良する前段階として、予想ロジックやUIに触れず、取得可能なボートレース関連データ、取得制約、保存・正規化方針を整理する。

## 確認したURL

公式サイト:

- `https://www.boatrace.jp/robots.txt`
- `https://www.boatrace.jp/owpc/pc/extra/policy.html`
- `https://www.boatrace.jp/owpc/pc/race/index?hd=YYYYMMDD`
- `https://www.boatrace.jp/owpc/pc/race/racelist?hd=YYYYMMDD&jcd=JJ&rno=R`
- `https://www.boatrace.jp/owpc/pc/race/odds3t?hd=YYYYMMDD&jcd=JJ&rno=R`
- `https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=YYYYMMDD&jcd=JJ&rno=R`
- `https://www.boatrace.jp/owpc/pc/race/raceresult?hd=YYYYMMDD&jcd=JJ&rno=R`
- `https://www.boatrace.jp/owpc/pc/race/resultlist?hd=YYYYMMDD&jcd=JJ`

公式ダウンロード系:

- `https://www1.mbrace.or.jp/robots.txt`
- `https://www1.mbrace.or.jp/od2/B/dindex.html`
- `https://www1.mbrace.or.jp/od2/K/dindex.html`
- `https://www1.mbrace.or.jp/od2/B/202606/mday.html`
- `https://www1.mbrace.or.jp/od2/K/202606/mday.html`
- `https://www1.mbrace.or.jp/od2/B/202606/b260616.lzh`
- `https://www1.mbrace.or.jp/od2/K/202606/k260616.lzh`

非公式API候補:

- `https://boatraceopenapi.github.io/programs/v3/YYYY/YYYYMMDD.json`
- `https://boatraceopenapi.github.io/previews/v3/YYYY/YYYYMMDD.json`
- `https://boatraceopenapi.github.io/results/v3/YYYY/YYYYMMDD.json`

既存ページの確認:

- `manshu.html` は `boatraceopenapi.github.io` の `programs/v2` と `results/v2` をブラウザ上で参照している。
- `manshu.html` と `manshu/2026-06-16.html` は同一内容で、日別静的HTMLをトップへコピーする運用に見える。
- 生成スクリプトや元データベースは、このリポジトリ内には見当たらない。

## 利用条件・注意点

`www.boatrace.jp/robots.txt` と `www1.mbrace.or.jp/robots.txt` は、どちらも `User-agent: *` に対して明示的な `Disallow` は空だった。ただし、これは無制限取得を許す意味ではない。

公式サイトのサイトポリシーでは、主に以下の点に注意が必要:

- コンテンツは著作権等で保護され、法令上認められる範囲を超える複製、改ざん、頒布などはできない。
- 不正アクセス、大量の情報送受信、大量アクセスなど、サイト運営に支障を与える行為は禁止されている。
- 掲載情報の正確性、有用性、確実性、最新性などは保証されない。
- コンテンツやURLは予告なく変更、削除、中断される場合がある。
- 外部リンクや第三者サイトはそれぞれの利用条件に従う必要がある。

このリポジトリでの実装方針:

- 取得は指定日単位に限定する。
- デフォルトでは開催一覧1ページだけ取得する。
- レース詳細、オッズ、直前情報、結果は明示オプションがある時だけ取得する。
- 同一URLは必ず `data/raw/YYYYMMDD/` のキャッシュを再利用する。
- `--force` 指定時だけキャッシュを無視して再取得する。
- 1リクエストごとにデフォルト1秒以上待つ。
- 並列取得は実装しない。
- 失敗時は指数バックオフで少数回だけ再試行する。
- User-Agentを明示する。
- raw HTMLの再配布を目的にしない。ローカル分析・検証用のキャッシュとして扱う。
- 公開ページや投稿文に舟券購入を推奨する表現は追加しない。

## データ項目の棚卸し

| 項目 | 公式画面系 | 公式DL系 | 非公式API候補 | 今回の正規化 |
|---|---|---|---|---|
| 開催日 | index/racelist/result URL | B/Kファイル | programs/results | `date` |
| レース場コード jcd | index内リンク | 場コード相当 | `race_stadium_number` 等 | `venues[].jcd` |
| レース場名 | index画像alt/header | 場コード対応表が必要 | 場名あり | `venues[].name` |
| グレード | indexのCSS class/title | 番組表側に含まれる可能性 | 含まれる場合あり | `venues[].grade` |
| 開催タイトル | index/header | 番組表 | programs | `venues[].title` |
| 日目 | index | 番組表 | programs | `venues[].day_label` |
| 開催状態 | index | 成績側 | results | `venues[].status` |
| レース番号 | racelist/result URL | B/K | programs/results | `races[].race_no` |
| レース名 | racelist | B | programs | `races[].race_name` |
| 締切予定時刻 | index/racelist | B | programs | `races[].deadline` |
| 距離 | racelist | B | programs | `races[].distance_m` |
| 安定板 | racelist/beforeinfoに表示される場合 | B/K要確認 | previewsに含まれる場合あり | `conditions.stabilizer` |
| 進入固定 | racelistに表示される場合 | B | programsに含まれる場合あり | `conditions.fixed_entry` |
| 枠番 | racelist | B | programs | `boats[].lane` |
| 登録番号 | racelist | B | programs | `boats[].registration_no` |
| 選手名 | racelist | B | programs | `boats[].name` |
| 級別 | racelist | B | programs | `boats[].class` |
| 支部・出身地 | racelist | B | programsに含まれる場合あり | `branch`, `birthplace` |
| 年齢・体重 | racelist/beforeinfo | B | programs/previews | `age`, `weight_kg` |
| F数・L数 | racelist | B | programs | `f_count`, `l_count` |
| 平均ST | racelist | B | programs | `avg_st` |
| 全国勝率・2連率・3連率 | racelist | B | programs | `national` |
| 当地勝率・2連率・3連率 | racelist | B | programs | `local` |
| モーター番号・2連率・3連率 | racelist | B | programs | `motor` |
| ボート番号・2連率・3連率 | racelist | B | programs | `boat` |
| 展示タイム | beforeinfo | なし/別系統 | previews | `preview.exhibition_time` |
| チルト | beforeinfo | なし/別系統 | previews | `preview.tilt` |
| 調整体重 | beforeinfo | なし/別系統 | previews | `preview.adjust_weight` |
| 部品交換 | beforeinfo | なし/別系統 | previews | `preview.parts_changed` |
| 展示進入 | beforeinfo | なし/別系統 | previews | `preview.exhibition_entry` |
| 展示ST | beforeinfo | なし/別系統 | previews | `preview.exhibition_st` |
| 天候 | beforeinfo | Kに含まれる可能性 | previews/results | `weather.weather` |
| 風向 | beforeinfoはCSS class中心 | Kに含まれる可能性 | previews/results | `weather.wind_direction` |
| 風速 | beforeinfo | Kに含まれる可能性 | previews/results | `weather.wind_speed_m` |
| 波高 | beforeinfo | Kに含まれる可能性 | previews/results | `weather.wave_cm` |
| 気温 | beforeinfo | Kに含まれる可能性 | previews/results | `weather.air_temp_c` |
| 水温 | beforeinfo | Kに含まれる可能性 | previews/results | `weather.water_temp_c` |
| 3連単オッズ | odds3t | なし | なし/保証なし | `odds.trifecta` |
| 3連単結果 | raceresult/resultlist | K | results | `result.trifecta` |
| 払戻金 | raceresult/resultlist | K | results | `result.payout_yen` |
| 人気 | raceresult | Kに含まれる場合あり | resultsに含まれる場合あり | `result.popularity` |
| 返還・欠場・中止 | raceresult/resultlist | K | results | `result.refunds`, `is_canceled` |

## 取得できるデータと制約

今回のサンプル `2026-06-16 桐生2R` では、公式画面系から以下を正規化できた:

- 開催一覧: 12場
- 出走表: 6艇分
- 3連単オッズ: 120点
- 直前情報: 展示タイム、チルト、調整体重、展示進入、展示ST、気象
- 結果: 3連単 `1-2-3`、払戻金 `1000` 円、人気 `2`

2026-06-17追記: 公式ダウンロード系の `B`（番組表）と `K`（競走成績）を確認し、以下を取得できることを確認した。

- `B/YYYYMM/bYYMMDD.lzh`: 場、開催タイトル、日次、レース名、距離、締切予定、6艇分の登録番号・選手名・級別・支部・年齢・体重・全国勝率/2連率・当地勝率/2連率・モーター番号/2連率・ボート番号/2連率。
- `K/YYYYMM/kYYMMDD.lzh`: 場、レースごとの天候・風向・風速・波高、展示タイム、展示進入、展示ST、着順、決まり手、3連単結果、払戻金、人気、F/Lなどの返還候補。
- 公式DLは `.lzh` 形式で、ローカルでは `lha` により展開できる。取得スクリプトは `.lzh` とUTF-8変換済みTXTを `data/raw/YYYYMMDD/` に保存する。
- 公式DLのBファイルでは、全国3連率、当地3連率、モーター3連率、ボート3連率、F/L数、平均STが欠ける場合がある。必要な場合は公式画面または非公式APIを補助として明示的に扱う。

制約:

- 公式画面HTMLは構造変更に弱い。CSS class名やテーブル構造変更でパーサ修正が必要になる。
- 風向は現状 `is-wind12` のようなCSS class値として保存している。方角名への変換表は別途定義が必要。
- 公式DL系は機械処理に向く可能性が高いが、古いframesetページからファイルリンクを追う必要があり、今回の実装対象からは外した。
- オッズは画面系にあり、公式DL系や非公式APIでは同等のリアルタイム性を期待しない。
- 公式サイトの掲載情報は保証されず、URLやHTML構造も変わる可能性がある。

## 公式ダウンロードと画面スクレイピングの違い

公式ダウンロード系:

- 長期・大量の過去分析には画面スクレイピングより向いている。
- 番組表と競走成績に分かれている。
- 実ファイルは `B/YYYYMM/bYYMMDD.lzh` と `K/YYYYMM/kYYMMDD.lzh` の形式で月別に配置される。
- 画面HTMLより安定した固定幅テキストに近く、分析用の過去データ取得に使いやすい。
- 直前情報、展示、オッズのリアルタイム取得には向かない可能性がある。
- 3連単オッズ120点は含まれないため、オッズ分析は公式画面系の低頻度・指定範囲取得に分ける。

公式画面系:

- 当日ページ、直前情報、オッズ、結果を同じURL規則で取得できる。
- 人間向けHTMLなので、取得頻度とキャッシュに強く配慮する必要がある。
- HTML変更への追随コストがある。
- 今回は「低頻度の指定日・指定場・指定R取得」として実装する。

## 非公式APIを使う場合の注意点

BoatraceOpenAPI は既存 `manshu.html` でも使われているが、公式APIではない。使う場合は以下をREADMEや画面に明記すること。

- 非公式である。
- リアルタイム性は保証されない。
- 正確性・完全性は保証されない。
- 欠損や仕様変更がありうる。
- 公式画面/公式DLの代替ではなく、比較・フォールバック・開発時の軽量参照として扱う。

## 推奨する実装方針

短期:

- 公式画面系の取得は今回追加した `scripts/fetch_boatrace_data.py` を使う。
- `--details` 等は必要な日・場・Rだけに絞る。
- `data/raw/YYYYMMDD/` を一次キャッシュとして保存する。
- `scripts/normalize_boatrace_data.py` で `data/normalized/YYYYMMDD.json` に変換する。
- 予想ロジックやUIは、この正規化JSONの品質確認が終わるまで変更しない。

中期:

- 公式DL系のB/Kファイルを主入力にし、過去データの一括分析はDL系を優先する。
- 画面系は当日・直前・オッズの補完に限定する。
- HTMLパーサにはサンプルfixtureを追加し、公式HTML変更を検知できるようにする。

長期:

- 正規化スキーマを固定し、既存の静的HTML生成フローが参照できるJSONを別途生成する。
- GitHub Pages用には、生HTMLではなく軽量な正規化JSONだけを配置する。
- 公開表示は娯楽・分析用途に限定し、舟券購入推奨の文言は入れない。

## 次フェーズで改善できる予測ロジック案

今回は実装しない。次フェーズ候補としてのみ記録する。

- 直前情報の展示タイム、チルト、展示ST、進入を特徴量化する。
- 公式オッズから人気の偏り、過小評価候補、直前オッズ変化を特徴量化する。
- 公式DL系の過去データで、画面取得データの欠損・ズレを検証する。
- 場、グレード、レース番号、気象、安定板、進入固定ごとの層別キャリブレーションを行う。
- 学習期間と検証期間を分け、既存READMEのOOS規律に合わせる。
- 万舟率と回収率を分けて評価し、購入推奨ではなく「荒れやすさ」指標として表示する。
