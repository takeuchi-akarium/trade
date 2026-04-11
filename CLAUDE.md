# CLAUDE.md

## このリポジトリについて

BTC（暗号資産）および日本株を対象とした自動売買システムの開発リポジトリ。
バックテスト → ペーパートレード → 本番自動売買の順に段階的に構築する。

## 技術スタック

- **言語**: Python 3.14
- **主要ライブラリ**: pandas, numpy, plotly, requests
- **データソース**: Binance公開API（BTC）、J-Quants（日本株、将来）
- **仮想環境**: `.venv/`

## 開発コマンド

```bash
# 仮想環境有効化
.venv/Scripts/activate

# データ取得
python src/fetch_btc.py

# 依存関係インストール
python -m pip install -r requirements.txt
```

## シミュレーション

全戦略は `src/strategies/` にパッケージ化されている。共通CLIで実行し、結果はFlaskダッシュボードで確認する。

```bash
# 戦略一覧
python src/simulator/runner.py list

# バックテスト（結果は data/simulations/ にJSON保存）
python src/simulator/runner.py run --strategy rsi --symbol BTCUSDT --interval 1d
python src/simulator/runner.py run --strategy btc_ma --symbol BTCUSDT --years 3

# 複数戦略比較
python src/simulator/runner.py compare --strategies rsi,bb,ema,vwap --symbol BTCUSDT

# リアルタイムペーパートレード（常駐、Ctrl+Cで停止）
python src/simulator/runner.py live --strategy rsi --symbol BTCUSDT --interval 5m

# ダッシュボード起動 → ブラウザで確認
python src/web/app.py
# http://localhost:5000             ← メインダッシュボード
# http://localhost:5000/simulations ← シミュレーション結果
```

### 登録済み戦略

| 名前 | カテゴリ | 説明 |
|------|---------|------|
| `rsi` | short_term | RSI逆張り |
| `bb` | short_term | ボリンジャーバンド |
| `ema` | short_term | EMAクロス |
| `vwap` | short_term | VWAP乖離 |
| `btc_ma` | long_term | BTC MAクロス (Mid-Band Exit) |
| `dual_momentum` | long_term | デュアルモメンタム (GEM) |
| `leadlag` | long_term | 日米リードラグ (PCA SUB) |
| `pair_bb` | pair | ペアトレード スプレッドBB |
| `pair_ema` | pair | ペアトレード スプレッドEMA |

### 新しい戦略の追加方法

1. `src/strategies/新戦略/` フォルダを作成
2. `__init__.py` に `Strategy` を継承したクラスを実装し `register()` を呼ぶ
3. `src/strategies/__init__.py` に `import strategies.新戦略` を追加
4. 完了 — CLIから使える

## ルール

@.claude/rules/general.md
@.claude/rules/security.md

## 利用可能なエージェント

| エージェント | 説明 |
|------------|------|
| `researcher` | コードベースの調査・分析（影響範囲の特定、パターン分析など） |
| `strategist` | 投資・トレード戦略の立案・評価（アイデア出し、リスク評価） |
| `builder` | シミュレーション・バックテスト・自動売買のコード実装 |
| `backtester` | バックテスト実行と結果分析（戦略の定量評価・比較） |
| `test-runner` | テスト実行と失敗分析 |

## 利用可能なスキル

| コマンド | 説明 |
|---------|------|
| `/commit` | コミットメッセージを生成してコミット |
| `/review` | コードレビューを実施 |
| `/ship` | レビュー→コミット→PR作成 |

## メモリ

Claude Codeはプロジェクト固有のメモリを `~/.claude/projects/<path>/memory/` に保存できる。
次回の会話でも活かすべき情報は積極的に保存する。

| 種別 | 保存する情報の例 |
|------|----------------|
| `user` | ユーザーの役割・技術レベル・好み |
| `feedback` | 「こうしてほしい／やめてほしい」という指示 |
| `project` | 背景・制約・意思決定の経緯 |
| `reference` | 外部ドキュメント・Slack・Linear などのリンク |
