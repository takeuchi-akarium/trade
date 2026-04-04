#!/bin/bash
# PostToolUse フック: ファイル編集後に自動フォーマット

if ! command -v jq &>/dev/null; then
  exit 0
fi

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
if [[ "$TOOL" != "Edit" && "$TOOL" != "Write" ]]; then
  exit 0
fi

FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  exit 0
fi

EXT="${FILE##*.}"

# Prettierが使えるファイル形式のみフォーマット
case "$EXT" in
  js|jsx|ts|tsx|json|css|scss|md)
    if command -v prettier &>/dev/null; then
      prettier --write "$FILE" 2>/dev/null
    fi
    ;;
  py)
    if command -v black &>/dev/null; then
      black "$FILE" 2>/dev/null
    fi
    ;;
esac

exit 0
