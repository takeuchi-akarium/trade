"""
マクロ指標コレクター

取得する指標:
  - Fear & Greed Index (alternative.me, 無料・認証不要)
  - VIX              (Yahoo Finance, 無料・認証不要)
"""

import requests


def get_fear_greed() -> dict:
    """
    暗号資産 Fear & Greed Index を取得
    戻り値例: {"value": 72, "label": "Greed"}
    """
    resp = requests.get(
        "https://api.alternative.me/fng/?limit=1",
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()["data"][0]
    return {
        "value": int(data["value"]),
        "label": data["value_classification"],
    }


def get_vix() -> float | None:
    """
    VIX（恐怖指数）の直近値を取得
    取得失敗時は None を返す
    """
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return None
