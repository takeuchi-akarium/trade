# trade

BTC（暗号資産）および日本株を対象とした自動売買システム。
バックテスト → ペーパートレード → 本番自動売買の順に段階的に構築する。

## セットアップ

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

## 使い方

```bash
# BTCデータ取得（Binance公開API、口座不要）
python src/fetch_btc.py

# バックテスト（移動平均クロス戦略）
python src/backtest.py
```

## 構成

```
src/
├── fetch_btc.py   # データ取得（日足・1時間足、ページネーション対応）
├── backtest.py    # バックテスト（MAクロス戦略、HTMLチャート出力）
└── optimize.py    # MAパラメータ最適化（グリッドサーチ）
data/              # 取得データ・チャート（.gitignore対象）
```

## ロードマップ

- [x] データ取得（Binance公開API）
- [x] バックテスト（移動平均クロス）
- [x] パラメータ最適化（グリッドサーチ、ヒートマップ）
- [ ] 複数戦略の比較
- [ ] 本番自動売買
