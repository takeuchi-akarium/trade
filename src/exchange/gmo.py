"""
GMOコイン REST API 実装

公式ドキュメント: https://api.coin.z.com/docs/
認証: HMAC-SHA256 (API-KEY, API-TIMESTAMP, API-SIGN)
"""

import hashlib
import hmac
import json
import os
import time

import requests

from exchange.base import Exchange

PUBLIC_URL = "https://api.coin.z.com/public"
PRIVATE_URL = "https://api.coin.z.com/private"


class GmoExchange(Exchange):

  def __init__(self, apiKey: str = None, apiSecret: str = None):
    self._apiKey = apiKey or os.environ.get("GMO_API_KEY", "")
    self._apiSecret = apiSecret or os.environ.get("GMO_API_SECRET", "")

  # ── 認証 ──

  def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
    message = timestamp + method + path + body
    return hmac.new(
      self._apiSecret.encode("utf-8"),
      message.encode("utf-8"),
      hashlib.sha256,
    ).hexdigest()

  def _headers(self, method: str, path: str, body: str = "") -> dict:
    timestamp = str(int(time.time() * 1000))
    return {
      "API-KEY": self._apiKey,
      "API-TIMESTAMP": timestamp,
      "API-SIGN": self._sign(timestamp, method, path, body),
      "Content-Type": "application/json",
    }

  # ── Private API ──

  def _checkApiKey(self) -> None:
    if not self._apiKey or not self._apiSecret:
      raise RuntimeError("GMO APIキーが未設定です (GMO_API_KEY / GMO_API_SECRET)")

  def _privateGet(self, path: str, params: dict = None) -> dict:
    self._checkApiKey()
    # 署名はパス部分のみ（クエリパラメータを含めない）
    headers = self._headers("GET", path)
    url = PRIVATE_URL + path
    if params:
      qs = "&".join(f"{k}={v}" for k, v in params.items())
      url = f"{url}?{qs}"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 0:
      raise RuntimeError(f"GMO API error: {data}")
    return data.get("data", data)

  def _privatePost(self, path: str, body: dict) -> dict:
    self._checkApiKey()
    url = PRIVATE_URL + path
    bodyStr = json.dumps(body)
    headers = self._headers("POST", path, bodyStr)
    resp = requests.post(url, headers=headers, data=bodyStr, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 0:
      raise RuntimeError(f"GMO API error: {data}")
    return data.get("data", data)

  # ── Public API ──

  def getTicker(self, symbol: str = "BTC") -> dict:
    resp = requests.get(f"{PUBLIC_URL}/v1/ticker?symbol={symbol}", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 0:
      raise RuntimeError(f"GMO API error: {data}")
    items = data.get("data", [])
    if not items:
      raise RuntimeError(f"No ticker data for {symbol}")
    t = items[0]
    return {
      "ask": float(t.get("ask", 0)),
      "bid": float(t.get("bid", 0)),
      "last": float(t.get("last", 0)),
      "volume": float(t.get("volume", 0)),
      "high": float(t.get("high", 0)),
      "low": float(t.get("low", 0)),
      "timestamp": t.get("timestamp", ""),
    }

  # ── 残高 ──

  def getBalance(self) -> dict:
    data = self._privateGet("/v1/account/assets")
    result = {}
    for item in data:
      # APIによって大文字/小文字が混在する場合があるため大文字に統一
      sym = item.get("symbol", "").upper()
      result[sym] = {
        "amount": float(item.get("amount", 0)),
        "available": float(item.get("available", 0)),
      }
    return result

  # ── 注文 ──

  def orderMarket(self, symbol: str, side: str, size: float) -> dict:
    body = {
      "symbol": symbol,
      "side": side.upper(),
      "executionType": "MARKET",
      "size": str(size),
    }
    return self._privatePost("/v1/order", body)

  def orderLimit(self, symbol: str, side: str, price: float, size: float) -> dict:
    body = {
      "symbol": symbol,
      "side": side.upper(),
      "executionType": "LIMIT",
      "price": str(int(price)),
      "size": str(size),
    }
    return self._privatePost("/v1/order", body)

  def orderStop(self, symbol: str, side: str, stopPrice: float, size: float) -> dict:
    """
    逆指値注文。stopPriceに達したら成行で執行される。
    損切り用: side=SELL, stopPrice=買値の-N%
    """
    body = {
      "symbol": symbol,
      "side": side.upper(),
      "executionType": "STOP",
      "stopPrice": str(int(stopPrice)),
      "size": str(size),
    }
    return self._privatePost("/v1/order", body)

  # ── 注文管理 ──

  def getActiveOrders(self, symbol: str, page: int = 1, count: int = 100) -> list[dict]:
    data = self._privateGet("/v1/activeOrders", {
      "symbol": symbol,
      "page": page,
      "count": count,
    })
    return data.get("list", []) if isinstance(data, dict) else data

  def cancelOrder(self, orderId: str) -> dict:
    return self._privatePost("/v1/cancelOrder", {"orderId": int(orderId)})

  def getExecutions(self, symbol: str = None, orderId: str = None) -> list[dict]:
    params = {}
    if orderId:
      params["orderId"] = orderId
    elif symbol:
      params["symbol"] = symbol
    data = self._privateGet("/v1/executions", params)
    return data.get("list", []) if isinstance(data, dict) else data
