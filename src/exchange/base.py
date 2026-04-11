"""
取引所API共通インターフェース

全取引所はこのクラスを継承して実装する。
"""

from abc import ABC, abstractmethod


class Exchange(ABC):

  @abstractmethod
  def getTicker(self, symbol: str) -> dict:
    """
    現在価格を取得。
    Returns: {"ask": float, "bid": float, "last": float, "volume": float}
    """
    ...

  @abstractmethod
  def getBalance(self) -> dict:
    """
    残高を取得。
    Returns: {"JPY": float, "BTC": float, ...}
    """
    ...

  @abstractmethod
  def orderMarket(self, symbol: str, side: str, size: float) -> dict:
    """
    成行注文。
    side: "BUY" or "SELL"
    Returns: {"orderId": str, ...}
    """
    ...

  @abstractmethod
  def orderLimit(self, symbol: str, side: str, price: float, size: float) -> dict:
    """
    指値注文。
    Returns: {"orderId": str, ...}
    """
    ...

  @abstractmethod
  def orderStop(self, symbol: str, side: str, stopPrice: float, size: float) -> dict:
    """
    逆指値注文。stopPriceに達したら成行で執行される。
    Returns: {"orderId": str, ...}
    """
    ...

  @abstractmethod
  def getActiveOrders(self, symbol: str) -> list[dict]:
    """有効注文一覧"""
    ...

  @abstractmethod
  def cancelOrder(self, orderId: str) -> dict:
    """注文キャンセル"""
    ...

  @abstractmethod
  def getExecutions(self, symbol: str, orderId: str = None) -> list[dict]:
    """約定一覧"""
    ...
