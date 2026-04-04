# CLAUDE.md

## このリポジトリについて

BTC（暗号資産）および日本株を対象とした自動売買システムの開発リポジトリ。
バックテスト → ペーパートレード → 本番自動売買の順に段階的に構築する。

## 技術スタック

- **言語**: Python 3.14
- **主要ライブラリ**: pandas, numpy, matplotlib, requests
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

## ルール

@.claude/rules/general.md
@.claude/rules/security.md

## 利用可能なエージェント

| エージェント | 説明 |
|------------|------|
| `researcher` | コードベースの調査・分析（影響範囲の特定、パターン分析など） |

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
