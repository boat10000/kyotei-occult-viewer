# research_v2 Manshu Cluster Validation

万舟レースで代表パターンを作り、全レースを分母として各クラスタの万舟率とリフトを計算しました。

## 手法比較

| 手法 | クラスタ数 | silhouette | 新規割当 |
| --- | ---: | ---: | --- |
| KMeans | 3 | 0.125441 | True |
| GaussianMixture | 3 | 0.11044 | True |
| Agglomerative | 3 | 0.104065 | False |
| KMeans | 4 | 0.11205 | True |
| GaussianMixture | 4 | 0.11762 | True |
| Agglomerative | 4 | 0.107133 | False |
| KMeans | 5 | 0.109601 | True |
| GaussianMixture | 5 | 0.077104 | True |
| Agglomerative | 5 | 0.105813 | False |
| KMeans | 6 | 0.101403 | True |
| GaussianMixture | 6 | 0.080795 | True |
| Agglomerative | 6 | 0.101072 | False |
| KMeans | 7 | 0.095439 | True |
| GaussianMixture | 7 | 0.066721 | True |
| Agglomerative | 7 | 0.098222 | False |

## 採用

- 採用手法: KMeans k=3
- 類似度閾値: 7.095019
- `unknown` は無理に割り当てない低類似レースです。
- クラスタ情報は最終テストでランキング改善が確認されるまで本番利用しません。
