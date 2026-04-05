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
from common.logger import log, cleanup

BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


def get_btc_price() -> float:
    resp = requests.get(BINANCE_PRICE_URL, params={"symbol": "BTCUSDT"}, timeout=5)
    resp.raise_for_status()
    return float(resp.json()["price"])


def run() -> None:
    try:
        price = get_btc_price()
        log("5m_price", f"BTC: ${price:,.0f}")
    except Exception as e:
        log("5m_price", f"ERROR: {e}")
    cleanup()


if __name__ == "__main__":
    run()
