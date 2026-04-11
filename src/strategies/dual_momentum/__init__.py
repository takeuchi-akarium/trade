"""
デュアルモメンタム (GEM) 戦略

月次リバランス。SPY vs EFA の相対モメンタム + Tビルとの絶対モメンタム。
"""

import pandas as pd
import numpy as np
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


class DualMomentumStrategy(Strategy):
  name = "dual_momentum"
  description = "デュアルモメンタム (GEM)"
  category = "long_term"
  defaultParams = {
    "lookback": 12,
    "start": "2005-01-01",
  }

  def fetchData(self, symbol: str = "", interval: str = "", **kwargs) -> pd.DataFrame:
    from strategies.dual_momentum.fetch_data import fetchPrices
    return fetchPrices()

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.dual_momentum.signal_generator import generateSignals
    p = self.getParams(**params)
    return generateSignals(data, lookback=p["lookback"])

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.dual_momentum.backtest import runBacktest, calcMonthlyMetrics
    p = self.getParams(**params)

    result = runBacktest(data, startDate=p["start"])
    m = result["metrics"]

    # 共通フォーマットに変換
    portDf = result["returns"]
    if len(portDf) > 0:
      cumRet = np.cumprod(1 + portDf["return"].values)
      equity = pd.Series(cumRet * 100_000, index=portDf.index)
    else:
      equity = pd.Series(dtype=float)

    # trades は月次リバランスなのでシグナル変化をトレードとして扱う
    trades = []
    signals = result["signals"]
    prevAsset = None
    for date, row in signals.iterrows():
      asset = row["signal"]
      if asset != prevAsset:
        if prevAsset is not None:
          trades.append({"datetime": date, "type": "sell", "reason": "rebalance",
                         "asset_from": prevAsset, "asset_to": asset})
        trades.append({"datetime": date, "type": "buy", "reason": "rebalance",
                       "asset": asset})
        prevAsset = asset

    metrics = {
      "totalReturn": m["totalReturn"],
      "finalValue": equity.iloc[-1] if len(equity) > 0 else 100_000,
      "totalTrades": len([t for t in trades if t["type"] == "sell"]),
      "winRate": m["hitRate"],
      "mdd": m["mdd"],
      "annualReturn": m["ar"],
      "annualRisk": m["risk"],
      "riskReturn": m["rr"],
    }

    return BacktestResult(
      strategyName=self.description,
      symbol="SPY/EFA/AGG",
      interval="monthly",
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


register(DualMomentumStrategy())
