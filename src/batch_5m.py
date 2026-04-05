"""
5分バッチ: 軽量な価格監視

タスクスケジューラで5分ごとに実行する。
現在は BTC 価格の取得のみ。
将来: 急騰/急落の異常検知 → 即時通知を追加予定。
"""

import sys
from pathlib import Path

# src/ をモジュール検索パスに追加
sys.path.insert(0, str(Path(__file__).parent))

import requests
from datetime import datetime

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


def get_btc_price() -> float:
    resp = requests.get(BINANCE_PRICE_URL, params={"symbol": "BTCUSDT"}, timeout=5)
    resp.raise_for_status()
    return float(resp.json()["price"])


def run() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        price = get_btc_price()
        print(f"[{now}] BTC: ${price:,.0f}")
    except Exception as e:
        print(f"[{now}] 価格取得失敗: {e}")


if __name__ == "__main__":
    run()
