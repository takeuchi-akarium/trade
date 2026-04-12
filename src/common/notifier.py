"""
通知モジュール: config.yaml の enabled フラグに従って各チャンネルへ送信

対応チャンネル:
  - discord  : Webhook URL 経由
  - log_file : TSVファイルへ追記
"""

import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def notify(message: str, config: dict) -> None:
    """設定で有効なチャンネルすべてに通知を送る"""
    channels = config.get("notifications", {})

    if channels.get("discord", {}).get("enabled"):
        _send_discord(message, channels["discord"].get("webhook_url", ""))

    if channels.get("log_file", {}).get("enabled"):
        _append_log(message, channels["log_file"].get("path", "data/signals/signal_log.tsv"))

    # LINE Notify は 2025年3月末でサービス終了済みのため無効化
    # if channels.get("line", {}).get("enabled"):
    #     _send_line(message, channels["line"].get("token", ""))


def _send_discord(message: str, webhook_url: str) -> None:
    if not webhook_url:
        print("  [Discord] webhook_url が未設定です（.env を確認）")
        return
    try:
        # Discord のメッセージ上限は 2000 文字。超える場合は分割送信
        chunks = _split_message(message, 2000)
        for chunk in chunks:
            resp = requests.post(webhook_url, json={"content": chunk}, timeout=10)
            resp.raise_for_status()
        print(f"  [Discord] 送信完了（{len(chunks)}通）")
    except Exception as e:
        print(f"  [Discord] 送信失敗: {e}")


def _split_message(message: str, limit: int) -> list[str]:
    """メッセージを limit 文字以内のチャンクに分割する（セクション区切りで分割）"""
    if len(message) <= limit:
        return [message]

    chunks = []
    current = ""
    # セクション（空行2つ）で分割を試みる
    sections = message.split("\n\n")
    for section in sections:
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # セクション単体が limit を超える場合は行単位で分割
            if len(section) > limit:
                lines = section.split("\n")
                current = ""
                for line in lines:
                    candidate = f"{current}\n{line}" if current else line
                    if len(candidate) <= limit:
                        current = candidate
                    else:
                        if current:
                            chunks.append(current)
                        current = line[:limit]
            else:
                current = section
    if current:
        chunks.append(current)
    return chunks


def _append_log(message: str, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(JST).isoformat()}\t{message}\n")


# LINE Notify は 2025年3月末でサービス終了済み。関数を残してあるが呼び出されない。
# def _send_line(message: str, token: str) -> None: ...
