"""
通知モジュール: config.yaml の enabled フラグに従って各チャンネルへ送信

対応チャンネル:
  - discord  : Webhook URL 経由
  - log_file : TSVファイルへ追記
  - line     : LINE Notify API 経由
"""

import requests
from datetime import datetime
from pathlib import Path


def notify(message: str, config: dict) -> None:
    """設定で有効なチャンネルすべてに通知を送る"""
    channels = config.get("notifications", {})

    if channels.get("discord", {}).get("enabled"):
        _send_discord(message, channels["discord"].get("webhook_url", ""))

    if channels.get("log_file", {}).get("enabled"):
        _append_log(message, channels["log_file"].get("path", "data/signals/signal_log.tsv"))

    if channels.get("line", {}).get("enabled"):
        _send_line(message, channels["line"].get("token", ""))


def _send_discord(message: str, webhook_url: str) -> None:
    if not webhook_url:
        print("  [Discord] webhook_url が未設定です（.env を確認）")
        return
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=5)
        resp.raise_for_status()
        print("  [Discord] 送信完了")
    except Exception as e:
        print(f"  [Discord] 送信失敗: {e}")


def _append_log(message: str, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}\t{message}\n")


def _send_line(message: str, token: str) -> None:
    if not token:
        print("  [LINE] token が未設定です（.env を確認）")
        return
    try:
        resp = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": f"\n{message}"},
            timeout=5,
        )
        resp.raise_for_status()
        print("  [LINE] 送信完了")
    except Exception as e:
        print(f"  [LINE] 送信失敗: {e}")
