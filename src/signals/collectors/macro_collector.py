"""
マクロ指標コレクター

取得する指標:
  - Fear & Greed Index (alternative.me, 無料・認証不要)
  - VIX              (Yahoo Finance, 無料・認証不要)
  - Gold (GC=F)      (Yahoo Finance, 無料・認証不要)
  - 10年債利回り (^TNX) (Yahoo Finance, 無料・認証不要)
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


def _fetchYahoo(symbol: str) -> float | None:
    """Yahoo Finance から直近価格を取得。失敗時はNone"""
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return None


def get_vix() -> float | None:
    """VIX（恐怖指数）の直近値を取得"""
    return _fetchYahoo("%5EVIX")


def get_gold() -> float | None:
    """ゴールド先物(GC=F)の直近価格を取得"""
    return _fetchYahoo("GC%3DF")


def get_tnx() -> float | None:
    """米10年債利回り(^TNX)の直近値を取得"""
    return _fetchYahoo("%5ETNX")


def get_gold_history(days: int = 60) -> list[float]:
    """ゴールド先物の日足終値をdays日分取得"""
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            params={"interval": "1d", "range": f"{days}d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return [c for c in closes if c is not None]
    except Exception:
        return []


def get_tnx_history(days: int = 30) -> list[float]:
    """米10年債利回りの日足終値をdays日分取得"""
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX",
            params={"interval": "1d", "range": f"{days}d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return [c for c in closes if c is not None]
    except Exception:
        return []


def get_fng_history(days: int = 40) -> list[int]:
    """Fear & Greed Index の日次値をdays日分取得（古い順）"""
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": days},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [int(d["value"]) for d in reversed(data)]
    except Exception:
        return []
