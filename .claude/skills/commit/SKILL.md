---
name: commit
description: ステージされた変更を分析して適切なコミットメッセージを生成し、コミットする
user-invocable: true
allowed-tools: Bash Read Glob Grep
argument-hint: "[追加のコンテキスト]"
---

ステージされた変更を分析して、適切なコミットメッセージを生成してコミットしてください。

## ステージされた変更
!`git diff --staged`

手順:
1. `git log --oneline -10` でこのリポジトリのコミットメッセージのスタイルを確認する
3. 変更の「何を」ではなく「なぜ」に焦点を当てたコミットメッセージを作成する
4. `git commit -m "..."` でコミットする（--no-verify は使わない）

追加コンテキスト: $ARGUMENTS

ルール:
- ステージされた変更がない場合はその旨を伝える
- コミットメッセージは既存のスタイル（日本語 or 英語）に合わせる
- プレフィックスが使われていれば従う（feat:, fix:, chore: など）
- Co-Authored-By は不要
