"""
リスク管理

5万円を守るための安全装置。注文前にチェックを通す。
"""

MIN_ORDER_BTC = 0.0001  # GMOコインの最小注文数量


class RiskManager:

  def __init__(self, config: dict):
    self._maxDailyLossPct = config.get("max_daily_loss_pct", 5)
    self._priceChangeLimit = config.get("price_change_limit", 10)
    self._capitalRatio = config.get("capital_ratio", 0.9)
    self._dailyStartEquity = None
    self._lastPrice = None

  def setDailyStart(self, equity: float) -> None:
    """1日の開始時点の資産を記録"""
    self._dailyStartEquity = equity

  def checkDailyLoss(self, currentEquity: float) -> tuple[bool, str]:
    """日次損失が制限を超えていないかチェック"""
    if self._dailyStartEquity is None:
      return True, ""
    lossPct = (currentEquity - self._dailyStartEquity) / self._dailyStartEquity * 100
    if lossPct <= -self._maxDailyLossPct:
      return False, f"日次損失制限超過: {lossPct:.1f}% (制限: -{self._maxDailyLossPct}%)"
    return True, ""

  def checkPriceChange(self, currentPrice: float) -> tuple[bool, str]:
    """前回価格からの急変動をチェック"""
    if self._lastPrice is None:
      self._lastPrice = currentPrice
      return True, ""
    changePct = abs(currentPrice - self._lastPrice) / self._lastPrice * 100
    self._lastPrice = currentPrice
    if changePct >= self._priceChangeLimit:
      return False, f"価格急変動: {changePct:.1f}% (制限: {self._priceChangeLimit}%)"
    return True, ""

  def calcOrderSize(self, balanceJpy: float, price: float) -> tuple[float, str]:
    """注文数量を計算。バッファを残して発注"""
    investable = balanceJpy * self._capitalRatio
    size = investable / price
    # 小数点以下4桁に切り捨て (GMOコインの最小単位)
    size = int(size * 10000) / 10000

    if size < MIN_ORDER_BTC:
      return 0, f"注文数量不足: {size} BTC < 最小 {MIN_ORDER_BTC} BTC (残高: {balanceJpy:.0f}円)"
    return size, ""

  def checkBeforeOrder(self, balanceJpy: float, price: float, currentEquity: float) -> tuple[bool, float, str]:
    """
    注文前の総合チェック。
    Returns: (ok, size, message)
    """
    # 日次損失チェック
    ok, msg = self.checkDailyLoss(currentEquity)
    if not ok:
      return False, 0, msg

    # 価格急変動チェック
    ok, msg = self.checkPriceChange(price)
    if not ok:
      return False, 0, msg

    # 注文数量チェック
    size, msg = self.calcOrderSize(balanceJpy, price)
    if size == 0:
      return False, 0, msg

    return True, size, ""
