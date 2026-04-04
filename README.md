# Claude Code テンプレート

新しいプロジェクトに `.claude/` と `CLAUDE.md` をコピーして使う Claude Code 設定テンプレート。

## 使い方

```bash
TEMPLATE=/path/to/template
PROJECT=/your/project

cp -r $TEMPLATE/.claude $PROJECT/
cp $TEMPLATE/CLAUDE.md $PROJECT/

chmod +x $PROJECT/.claude/hooks/*.sh
```

コピー後、`CLAUDE.md` の TODO 部分をプロジェクトに合わせて書き換える。

## ファイル構成

```
.claude/
├── settings.json          # フック・権限・環境変数の設定
├── rules/
│   ├── general.md         # 一般的なコーディングルール
│   └── security.md        # セキュリティルール
├── skills/
│   ├── commit/            # /commit: コミットメッセージ生成
│   ├── review/            # /review: コードレビュー
│   └── ship/              # /ship: レビュー→コミット→PR作成
├── agents/
│   └── researcher/        # researcher エージェント
└── hooks/
    ├── protect-files.sh   # 保護ファイルへの書き込みブロック
    ├── post-edit.sh       # 編集後の自動フォーマット
    └── notify.sh          # タスク完了・入力待ちの通知
CLAUDE.md                  # プロジェクト概要・ルール・スキル一覧
```

## カスタマイズ

- `settings.json`: 保護ファイルリスト・ツール権限を調整
- `hooks/protect-files.sh`: `PROTECTED_PATTERNS` に保護したいファイルを追加
- `hooks/post-edit.sh`: 使用するフォーマッターを変更
- `rules/*.md`: プロジェクトのコーディング規約に合わせて編集
