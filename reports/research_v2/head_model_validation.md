# research_v2 Head Model Validation

既存 `head/axis/toss/opponent` は基準として保持し、別系統の候補 `candidate_logit_v1` を比較しました。本番ランキングには接続していません。

## 最終テスト strict TOP10

- 既存role直前 head2捕捉率: 36.67%
- 候補logit朝 head2捕捉率: 54.67%
- 候補logit直前 head2捕捉率: 55.33%
- 候補logit直前 Brier: 0.78014
- 候補logit直前 log loss: 1.634063

## 判定

- この段階では本番採用しません。TOP10内で候補が既存roleを安定して上回るか、前向き検証が必要です。
- 結果列、払戻、人気、決まり手は特徴量に入れていません。
