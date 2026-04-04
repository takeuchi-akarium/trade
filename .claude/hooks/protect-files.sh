#!/bin/bash
# PreToolUse フック: 保護ファイルへの書き込みをブロックする

if ! command -v jq &>/dev/null; then
  exit 0
fi

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [ -z "$FILE" ]; then
  exit 0
fi

# 保護するファイル・パターンのリスト
# （ロックファイル・.env などの標準的な保護は settings.json の deny で管理）
# プロジェクト固有のカスタムパターンをここに追加する
# 例: "src/migrations/*.sql"
PROTECTED_PATTERNS=(
)

if [ ${#PROTECTED_PATTERNS[@]} -eq 0 ]; then
  exit 0
fi

for pattern in "${PROTECTED_PATTERNS[@]}"; do
  if [[ "$FILE" == *"$pattern"* ]]; then
    echo "Protected file: $FILE cannot be directly edited by Claude. Edit manually if needed." >&2
    exit 2  # exit 2 でブロック（Claudeにフィードバック）
  fi
done

exit 0
