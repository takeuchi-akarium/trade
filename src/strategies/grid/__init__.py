"""
グリッドトレード戦略

レンジ内に等間隔の買い/売り注文を配置し、価格の上下動から利益を積む。
レンジ相場に強く、トレンド相場には逆指値で対応。
"""

import numpy as np
import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


BINANCE_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"}


def _isBinance(symbol: str) -> bool:
  return symbol.upper() in BINANCE_SYMBOLS or symbol.upper().endswith("USDT")


def _fetchData(symbol: str, interval: str = "1h", years: int = 1) -> pd.DataFrame:
  if _isBinance(symbol):
    from strategies.btc.fetch_btc import fetch_ohlcv
    return fetch_ohlcv(symbol=symbol.upper(), interval=interval, years=years)
  else:
    import yfinance as yf
    periodMap = {1: "1y", 2: "2y", 3: "5y"}
    period = periodMap.get(years, f"{years}y")
    if interval in ("1m", "5m", "15m"):
      period = "60d" if interval != "1m" else "7d"
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "datetime"
    for col in ("dividends", "stock_splits", "capital gains", "adj close"):
      df = df.drop(columns=[col], errors="ignore")
    return df[["open", "high", "low", "close", "volume"]]


def runGridBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  numGrids: int = 10,
  rangePct: float = 10.0,
  feePct: float = 0.01,
  stopLossPct: float = 15.0,
) -> tuple[list[dict], pd.Series]:
  """
  グリッドトレードのバックテスト。

  Args:
    df: OHLCVデータ（close列必須）
    initialCapital: 初期資金（円）
    numGrids: グリッド段数（上下合計）
    rangePct: 初期価格からのレンジ幅（±%）
    feePct: 手数料（%）
    stopLossPct: レンジ外の損切りライン（%）

  Returns:
    trades: 取引履歴
    equity: 資産推移
  """
  feeRate = feePct / 100
  prices = df["close"].values
  if len(prices) == 0:
    return [], pd.Series(dtype=float)

  # グリッド設定: 初期価格を中心にレンジを設定
  centerPrice = prices[0]
  rangeUpper = centerPrice * (1 + rangePct / 100)
  rangeLower = centerPrice * (1 - rangePct / 100)
  gridStep = (rangeUpper - rangeLower) / numGrids
  stopLossPrice = centerPrice * (1 - stopLossPct / 100)
  stopHighPrice = centerPrice * (1 + stopLossPct / 100)

  # グリッドレベルを設定
  gridLevels = [rangeLower + gridStep * i for i in range(numGrids + 1)]

  # 各グリッドの状態: 価格より下のグリッドは「買い待ち」、上は「売り待ち」
  # holdings[i] = True なら、gridLevels[i]で買ったポジションを保有中
  holdings = [False] * (numGrids + 1)
  capitalPerGrid = initialCapital / (numGrids // 2 + 1)

  capital = initialCapital
  totalBtc = 0.0
  trades = []
  equityList = []
  stopped = False

  # 初期状態: 現在価格より下のグリッドで買いポジションを持つ
  for i, level in enumerate(gridLevels):
    if level < centerPrice:
      size = capitalPerGrid / centerPrice
      fee = capitalPerGrid * feeRate
      capital -= (capitalPerGrid + fee)
      totalBtc += size
      holdings[i] = True

  for idx in range(len(prices)):
    price = prices[idx]
    dt = df.index[idx]

    # ストップロス判定
    if not stopped and (price <= stopLossPrice or price >= stopHighPrice):
      # 全ポジション決済
      if totalBtc > 0:
        proceeds = totalBtc * price
        fee = proceeds * feeRate
        capital += proceeds - fee
        trades.append({
          "datetime": dt, "type": "close", "side": "stop",
          "reason": "stop_loss", "price": price,
          "size": totalBtc, "fee": fee,
          "capitalAfter": capital,
        })
        totalBtc = 0
        holdings = [False] * (numGrids + 1)
      stopped = True

    if stopped:
      # レンジに戻ったらリセット
      if rangeLower * 1.02 < price < rangeUpper * 0.98:
        stopped = False
        # グリッドを再設定
        centerPrice = price
        rangeUpper = centerPrice * (1 + rangePct / 100)
        rangeLower = centerPrice * (1 - rangePct / 100)
        gridStep = (rangeUpper - rangeLower) / numGrids
        gridLevels = [rangeLower + gridStep * i for i in range(numGrids + 1)]
        stopLossPrice = centerPrice * (1 - stopLossPct / 100)
        stopHighPrice = centerPrice * (1 + stopLossPct / 100)
        holdings = [False] * (numGrids + 1)
        capitalPerGrid = capital / (numGrids // 2 + 1)

        for i, level in enumerate(gridLevels):
          if level < price and capital >= capitalPerGrid:
            size = capitalPerGrid / price
            fee = capitalPerGrid * feeRate
            capital -= (capitalPerGrid + fee)
            totalBtc += size
            holdings[i] = True

      equity = capital + totalBtc * price
      equityList.append((dt, equity))
      continue

    # 複利: 現在の総資産からグリッド1段あたりの資金を再計算
    currentEquity = capital + totalBtc * price
    nGridSlots = numGrids // 2 + 1
    capitalPerGrid = currentEquity / nGridSlots

    # グリッド約定チェック
    for i, level in enumerate(gridLevels):
      if holdings[i] and price >= level + gridStep:
        # 売り: このグリッドで買ったポジションを1段上で利確
        size = capitalPerGrid / level if level > 0 else 0
        if size > 0 and size <= totalBtc:
          proceeds = size * (level + gridStep)
          fee = proceeds * feeRate
          pnl = size * gridStep - fee
          capital += proceeds - fee
          totalBtc -= size
          holdings[i] = False
          trades.append({
            "datetime": dt, "type": "sell", "side": "grid",
            "price": level + gridStep, "size": size,
            "pnl": pnl, "fee": fee,
            "capitalAfter": capital,
          })

      elif not holdings[i] and price <= level and capital >= capitalPerGrid:
        # 買い: グリッドレベルまで下がったらエントリー
        size = capitalPerGrid / price
        fee = capitalPerGrid * feeRate
        capital -= (capitalPerGrid + fee)
        totalBtc += size
        holdings[i] = True
        trades.append({
          "datetime": dt, "type": "buy", "side": "grid",
          "price": price, "size": size, "fee": fee,
        })

    equity = capital + totalBtc * price
    equityList.append((dt, equity))

  equitySeries = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equitySeries


def calcGridMetrics(trades, equity, initialCapital):
  """グリッド戦略のメトリクス算出"""
  if len(equity) == 0:
    return {}

  finalValue = equity.iloc[-1]
  totalReturn = (finalValue - initialCapital) / initialCapital * 100

  sellTrades = [t for t in trades if t["type"] == "sell"]
  wins = [t for t in sellTrades if t.get("pnl", 0) > 0]
  nSells = len(sellTrades)

  grossProfit = sum(t["pnl"] for t in wins) if wins else 0
  losses = [t for t in sellTrades if t.get("pnl", 0) <= 0]
  grossLoss = abs(sum(t.get("pnl", 0) for t in losses)) if losses else 1
  pf = grossProfit / grossLoss if grossLoss > 0 else float("inf")

  peak = equity.cummax()
  dd = (equity - peak) / peak * 100
  mdd = float(dd.min())

  totalFees = sum(t.get("fee", 0) for t in trades)

  return {
    "totalReturn": totalReturn,
    "finalValue": finalValue,
    "totalTrades": nSells,
    "winRate": len(wins) / nSells * 100 if nSells > 0 else 0,
    "profitFactor": pf,
    "mdd": mdd,
    "totalFees": totalFees,
    "totalBuyTrades": len([t for t in trades if t["type"] == "buy"]),
  }


class GridStrategy(Strategy):
  name = "grid"
  description = "Grid Trade (range)"
  category = "short_term"
  defaultParams = {
    "capital": 50_000,
    "fee": 0.01,
    "numGrids": 10,
    "rangePct": 10.0,
    "stopLossPct": 15.0,
  }

  def fetchData(self, symbol: str, interval: str = "1h", **kwargs) -> pd.DataFrame:
    years = kwargs.get("years", 1)
    return _fetchData(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    # グリッドは個別シグナルではなくバックテスト内で処理するのでパススルー
    df = data.copy()
    df["signal"] = 0
    return df

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    p = self.getParams(**params)
    trades, equity = runGridBacktest(
      data,
      initialCapital=p["capital"],
      numGrids=p["numGrids"],
      rangePct=p["rangePct"],
      feePct=p["fee"],
      stopLossPct=p["stopLossPct"],
    )
    metrics = calcGridMetrics(trades, equity, p["capital"])

    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1h"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


register(GridStrategy())
