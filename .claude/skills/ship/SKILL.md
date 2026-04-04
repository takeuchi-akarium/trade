---
name: ship
description: 変更をレビュー・コミット・プッシュしてPRを作成する一連の作業を行う
user-invocable: true
disable-model-invocation: true
context: fork
allowed-tools: Bash Read Glob Grep
argument-hint: "[PRタイトルの補足]"
---

現在の変更をshipします。以下の手順を実行してください:

1. **ブランチ確認**: `git branch --show-current` で現在のブランチを確認する。`main` または `master` の場合は**中断してユーザーに確認する**（直接pushは行わない）
2. **状態確認**: `git status` と `git diff` で変更内容を確認
3. **テスト**: Read ツールで `CLAUDE.md` を読み、開発コマンドにテストコマンドが記載されていればそれを使う。なければ以下の順で検出（失敗したら中断）
   - `package.json` に `test` スクリプトがあれば `npm test`
   - `Makefile` に `test` ターゲットがあれば `make test`
   - `pytest.ini` / `pyproject.toml` があれば `pytest`
   - 見つからなければスキップ
4. **リント**: Read ツールで `CLAUDE.md` を読み、開発コマンドにリントコマンドが記載されていればそれを使う。なければ以下の順で検出
   - `package.json` に `lint` スクリプトがあれば `npm run lint`
   - `Makefile` に `lint` ターゲットがあれば `make lint`
   - 見つからなければスキップ
5. **コミット**: まだコミットされていない変更があればコミット
6. **プッシュ**: `git push` で現在のブランチをリモートへ
7. **PR作成**: `gh pr create` でPRを作成

PR作成時:
- タイトルは変更の概要を簡潔に
- 本文にはSummary（変更点）とTest plan（テスト方法）を含める
- 追加コンテキスト: $ARGUMENTS

注意:
- PRが既に存在する場合は作成をスキップ
- `gh` コマンドが使えない場合はプッシュまでで終了
