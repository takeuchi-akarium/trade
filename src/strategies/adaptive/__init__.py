"""
Adaptive Strategy — グリッド常時稼働 + トレンドブースト

グリッドは常に動かし、ボラ拡大時にトレンドポジションを追加で取る。
資金配分: グリッド70% / トレンド予備30%

モード切り替えでポジショ���全決済はしない（コスト削減）。
"""

import numpy as np
import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


def _fetchData(symbol: str, interval: str = "1h", years: int = 1) -> pd.DataFrame:
  if symbol.upper().endswith("USDT"):
    from strategies.btc.fetch_btc import fetch_ohlcv
    return fetch_ohlcv(symbol=symbol.upper(), interval=interval, years=years)
  else:
    import yfinance as yf
    period = {1: "1y", 2: "2y", 3: "5y"}.get(years, f"{years}y")
    if interval in ("1m", "5m", "15m"):
      period = "60d" if interval != "1m" else "7d"
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "datetime"
    for col in ("dividends", "stock_splits", "capital gains", "adj close"):
      df = df.drop(columns=[col], errors="ignore")
    return df[["open", "high", "low", "close", "volume"]]


def runAdaptiveBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  feePct: float = 0.01,
  numGrids: int = 10,
  rangePct: float = 5.0,
  gridStopPct: float = 8.0,
  emaShort: int = 10,
  emaLong: int = 40,
  trendStopPct: float = 5.0,
  gridRatio: float = 0.7,
) -> tuple[list[dict], pd.Series, dict]:
  """
  グリッド(70%) + トレンド(30%) 併用バックテスト。

  グリッドは常時稼働。
  EMAクロスでトレンドポジションを追加（予備資金から）。
  互いに干渉しない。
  """
  feeRate = feePct / 100
  prices = df["close"].values

  emaS = df["close"].ewm(span=emaShort, adjust=False).mean().values
  emaL = df["close"].ewm(span=emaLong, adjust=False).mean().values

  warmup = max(emaLong, 20) + 5
  if len(prices) <= warmup:
    return [], pd.Series(dtype=float), {}

  # === 資金配分 ===
  gridCap = initialCapital * gridRatio
  trendCap = initialCapital * (1 - gridRatio)

  # === Grid state ===
  centerPrice = prices[warmup]
  upper = centerPrice * (1 + rangePct / 100)
  lower = centerPrice * (1 - rangePct / 100)
  step = (upper - lower) / numGrids
  gridLevels = [lower + step * i for i in range(numGrids + 1)]
  gridHoldings = [False] * (numGrids + 1)
  gridBtc = 0.0
  gridCash = gridCap

  # 初期グリッドポジション
  cpg = gridCap / (numGrids // 2 + 1)
  for i, lv in enumerate(gridLevels):
    if lv < centerPrice and gridCash >= cpg:
      size = cpg / centerPrice
      fee = cpg * feeRate
      gridCash -= (cpg + fee)
      gridBtc += size
      gridHoldings[i] = True

  # === Trend state ===
  trendPos = 0   # +1=long, -1=short
  trendSize = 0.0
  trendEntry = 0.0
  trendCash = trendCap

  trades = []
  equityList = []
  stats = {"grid_sells": 0, "grid_buys": 0, "grid_stops": 0,
           "trend_trades": 0, "trend_stops": 0}

  for idx in range(warmup, len(prices)):
    price = prices[idx]
    dt = df.index[idx]

    # ====== GRID ======
    gridStopLow = centerPrice * (1 - gridStopPct / 100)
    gridStopHigh = centerPrice * (1 + gridStopPct / 100)

    if price <= gridStopLow or price >= gridStopHigh:
      # ストップ: 全グリッド決済 → 新価格で再設定
      if gridBtc > 0:
        proceeds = gridBtc * price
        fee = proceeds * feeRate
        gridCash += proceeds - fee
        gridBtc = 0
      stats["grid_stops"] += 1
      # 再設定
      centerPrice = price
      upper = centerPrice * (1 + rangePct / 100)
      lower = centerPrice * (1 - rangePct / 100)
      step = (upper - lower) / numGrids
      gridLevels = [lower + step * i for i in range(numGrids + 1)]
      gridHoldings = [False] * (numGrids + 1)
      cpg = gridCash / (numGrids // 2 + 1)
      for i, lv in enumerate(gridLevels):
        if lv < price and gridCash >= cpg:
          size = cpg / price
          fee = cpg * feeRate
          gridCash -= (cpg + fee)
          gridBtc += size
          gridHoldings[i] = True
    else:
      # 通常グリッド約定
      gridEquity = gridCash + gridBtc * price
      cpg = gridEquity / (numGrids // 2 + 1)
      for i, lv in enumerate(gridLevels):
        if gridHoldings[i] and price >= lv + step:
          size = cpg / lv if lv > 0 else 0
          if size > 0 and size <= gridBtc:
            proceeds = size * (lv + step)
            fee = proceeds * feeRate
            pnl = size * step - fee
            gridCash += proceeds - fee
            gridBtc -= size
            gridHoldings[i] = False
            stats["grid_sells"] += 1
            trades.append({"datetime": dt, "type": "sell", "side": "grid", "pnl": pnl, "price": price})
        elif not gridHoldings[i] and price <= lv and gridCash >= cpg:
          size = cpg / price
          fee = cpg * feeRate
          gridCash -= (cpg + fee)
          gridBtc += size
          gridHoldings[i] = True
          stats["grid_buys"] += 1

    # ====== TREND ======
    # SL判定
    if trendPos != 0:
      if trendPos == 1:
        plPct = (price - trendEntry) / trendEntry * 100
      else:
        plPct = (trendEntry - price) / trendEntry * 100
      if plPct <= -trendStopPct:
        if trendPos == 1:
          proceeds = trendSize * price
          fee = proceeds * feeRate
          trendCash = proceeds - fee
        else:
          pnl = trendSize * (trendEntry - price)
          fee = abs(trendSize * price) * feeRate
          trendCash += pnl - fee
        trendPos = 0
        trendSize = 0
        stats["trend_stops"] += 1
        trades.append({"datetime": dt, "type": "close", "side": "trend_sl", "price": price})

    # EMAクロス
    if idx > 0:
      emaDiff = emaS[idx] - emaL[idx]
      prevDiff = emaS[idx - 1] - emaL[idx - 1]

      # ゴールデンクロス → ロング
      if emaDiff > 0 and prevDiff <= 0:
        # ショート決済
        if trendPos == -1:
          pnl = trendSize * (trendEntry - price)
          fee = abs(trendSize * price) * feeRate
          trendCash += pnl - fee
          trendPos = 0
          trendSize = 0
        # ロングエントリー
        if trendPos == 0 and trendCash > 0:
          fee = trendCash * feeRate
          trendSize = (trendCash - fee) / price
          trendEntry = price
          trendPos = 1
          trendCash = 0
          stats["trend_trades"] += 1
          trades.append({"datetime": dt, "type": "open", "side": "long", "price": price})

      # デッドクロス → ショート
      elif emaDiff < 0 and prevDiff >= 0:
        # ロング決済
        if trendPos == 1:
          proceeds = trendSize * price
          fee = proceeds * feeRate
          trendCash = proceeds - fee
          trendPos = 0
          trendSize = 0
        # ショートエントリー
        if trendPos == 0 and trendCash > 0:
          fee = trendCash * feeRate
          trendCash -= fee
          trendSize = trendCash / price
          trendEntry = price
          trendPos = -1
          stats["trend_trades"] += 1
          trades.append({"datetime": dt, "type": "open", "side": "short", "price": price})

    # 時価評価
    gridEquity = gridCash + gridBtc * price
    if trendPos == 1:
      trendEquity = trendSize * price
    elif trendPos == -1:
      trendEquity = trendCash + trendSize * (trendEntry - price)
    else:
      trendEquity = trendCash
    equityList.append((dt, gridEquity + trendEquity))

  equitySeries = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equitySeries, stats


def calcAdaptiveMetrics(trades, equity, initialCapital, stats):
  if len(equity) == 0:
    return {}
  finalValue = equity.iloc[-1]
  totalReturn = (finalValue - initialCapital) / initialCapital * 100
  sellTrades = [t for t in trades if "pnl" in t]
  wins = [t for t in sellTrades if t.get("pnl", 0) > 0]
  nSells = len(sellTrades)
  peak = equity.cummax()
  dd = (equity - peak) / peak * 100
  mdd = float(dd.min())
  return {
    "totalReturn": totalReturn,
    "finalValue": finalValue,
    "totalTrades": stats.get("grid_sells", 0) + stats.get("trend_trades", 0),
    "winRate": len(wins) / nSells * 100 if nSells > 0 else 0,
    "mdd": mdd,
    **stats,
  }


class AdaptiveStrategy(Strategy):
  name = "adaptive"
  description = "Adaptive (Grid + Trend)"
  category = "short_term"
  defaultParams = {
    "capital": 50_000,
    "fee": 0.01,
    "numGrids": 10,
    "rangePct": 5.0,
    "gridStopPct": 8.0,
    "emaShort": 10,
    "emaLong": 40,
    "trendStopPct": 5.0,
    "gridRatio": 0.7,
  }

  def fetchData(self, symbol: str, interval: str = "1h", **kwargs) -> pd.DataFrame:
    years = kwargs.get("years", 1)
    return _fetchData(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    df = data.copy()
    df["signal"] = 0
    return df

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    p = self.getParams(**params)
    btParams = {k: v for k, v in p.items() if k in self.defaultParams and k not in ("capital", "fee")}
    trades, equity, stats = runAdaptiveBacktest(
      data, initialCapital=p["capital"], feePct=p["fee"], **btParams)
    metrics = calcAdaptiveMetrics(trades, equity, p["capital"], stats)
    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1h"),
      trades=trades, equity=equity, metrics=metrics,
      params=p, metadata=stats,
    )


register(AdaptiveStrategy())
