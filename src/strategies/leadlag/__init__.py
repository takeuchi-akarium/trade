"""
日米リードラグ戦略

米国セクターETFの前日リターンから日本セクターETFの予測シグナルを生成。
PCA部分空間正則化モデル。
"""

import pandas as pd
import numpy as np
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


class LeadlagStrategy(Strategy):
  name = "leadlag"
  description = "日米リードラグ (PCA SUB)"
  category = "long_term"
  defaultParams = {
    "backtestStart": "2015-01-01",
    "backtestEnd": "2025-12-31",
  }

  def fetchData(self, symbol: str = "", interval: str = "", **kwargs) -> pd.DataFrame:
    """alignReturnsまで済んだDataFrameを返す"""
    from strategies.leadlag.constants import US_TICKERS, JP_TICKERS
    from strategies.leadlag.fetch_data import fetchAllPrices, calcCcReturns, calcOcReturns
    from strategies.leadlag.calendar_align import alignReturns

    end = kwargs.get("end", "2026-12-31")
    usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end=end)
    usRetCc = calcCcReturns(usPrices, US_TICKERS)
    jpRetCc = calcCcReturns(jpPrices, JP_TICKERS)
    jpRetOc = calcOcReturns(jpPrices, JP_TICKERS)
    return alignReturns(usRetCc, jpRetCc, jpRetOc)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.leadlag.signal_generator import generateSignals
    return generateSignals(data)

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.leadlag.signal_generator import generateSignals
    from strategies.leadlag.portfolio import constructPortfolio
    from strategies.leadlag.metrics import calcMetrics
    from strategies.leadlag.constants import JP_TICKERS

    p = self.getParams(**params)
    start = p["backtestStart"]
    end = p["backtestEnd"]

    signals = generateSignals(data)
    signals = signals[(signals.index >= start) & (signals.index <= end)]

    jpOcCols = {f"jp_oc_{t}": t for t in JP_TICKERS}
    jpOcAligned = data[[c for c in jpOcCols if c in data.columns]].rename(columns=jpOcCols)
    jpOcAligned = jpOcAligned[(jpOcAligned.index >= start) & (jpOcAligned.index <= end)]

    portfolio = constructPortfolio(signals, jpOcAligned)
    m = calcMetrics(portfolio["port_return"])

    # equityカーブ (累積リターン → 絶対値)
    cumRet = np.cumprod(1 + portfolio["port_return"].values)
    equity = pd.Series(cumRet * 100_000, index=portfolio.index)

    metrics = {
      "totalReturn": m["totalReturn"],
      "finalValue": equity.iloc[-1] if len(equity) > 0 else 100_000,
      "totalTrades": len(portfolio),
      "winRate": m["hitRate"],
      "mdd": m["mdd"],
      "annualReturn": m["ar"],
      "annualRisk": m["risk"],
      "riskReturn": m["rr"],
    }

    return BacktestResult(
      strategyName=self.description,
      symbol="JP Sectors",
      interval="daily",
      trades=[],
      equity=equity,
      metrics=metrics,
      params=p,
    )


register(LeadlagStrategy())
