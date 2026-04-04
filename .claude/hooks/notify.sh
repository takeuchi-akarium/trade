#!/bin/bash
# Notification / Stop フック: デスクトップ通知を送る

TITLE="Claude Code"
MESSAGE="完了"

# イベント種別を取得（jq があれば JSON から、なければ引数 $1 をフォールバックに使う）
EVENT=""
if command -v jq &>/dev/null; then
  INPUT=$(cat)
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
fi
if [ -z "$EVENT" ]; then
  EVENT="${1:-}"
fi

case "$EVENT" in
  "Stop")         MESSAGE="タスク完了" ;;
  "Notification") MESSAGE="入力が必要です" ;;
esac

# macOS
if command -v osascript &>/dev/null; then
  osascript \
    -e 'on run argv' \
    -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"' \
    -e 'end run' \
    -- "$TITLE" "$MESSAGE"
fi

# Linux (libnotify)
if command -v notify-send &>/dev/null; then
  notify-send -- "$TITLE" "$MESSAGE"
fi

exit 0
