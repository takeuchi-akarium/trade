---
name: review
description: コードレビューを行い、問題点・改善点を指摘する
user-invocable: true
allowed-tools: Read Glob Grep Bash
argument-hint: "[ファイルパス or PR番号]"
---

以下のコードをレビューしてください: $ARGUMENTS

## レビュー対象
!`git diff --staged 2>/dev/null || git diff HEAD~1 2>/dev/null || echo "(変更なし)"`

レビューの観点:
1. **バグ・ロジックエラー**: 明らかな不具合や境界値の問題
2. **セキュリティ**: SQLインジェクション、XSS、認証の問題など
3. **パフォーマンス**: N+1クエリ、不要な再レンダリングなど重大な問題のみ
4. **可読性**: 理解しにくいコードや誤解を招く命名

形式:
- 重要度で分類: 🔴 必須修正 / 🟡 推奨 / 🟢 提案
- 問題点は具体的なファイル名と行番号で示す
- 良い点も1〜2個挙げる
- 些細なスタイル指摘は省く
