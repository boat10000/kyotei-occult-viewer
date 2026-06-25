# research_v2 Exhibition Incremental Validation

朝版と直前版を分離し、展示補正後の頭候補精度を比較しました。

## strict TOP10 / final_test / candidate_logit_v1

- 朝版 head2捕捉率: 54.67%
- 直前版 head2捕捉率: 55.33%
- 朝版 Brier: 0.781078
- 直前版 Brier: 0.78014

## 採用方針

- 直前版が朝版より悪化したセグメントでは展示補正を採用しません。
- 欠損展示データは0ではなく欠損として扱い、朝版へフォールバックします。
