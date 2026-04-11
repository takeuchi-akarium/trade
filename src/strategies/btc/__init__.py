"""
BTC MAクロス戦略 (Mid-Band Exit)

短期MA/長期MAのクロスでエントリー。
オプションでMid-Bandトレーリングストップを適用。
"""

import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


class BtcMaStrategy(Strategy):
  name = "btc_ma"
  description = "BTC MAクロス (Mid-Band Exit)"
  category = "long_term"
  defaultParams = {
    "short": 5,
    "long": 150,
    "threshold": 0.5,
    "capital": 100_000,
  }

  def fetchData(self, symbol: str = "BTCUSDT", interval: str = "1d", **kwargs) -> pd.DataFrame:
    from strategies.btc.fetch_btc import fetch_ohlcv
    years = kwargs.get("years", 3)
    return fetch_ohlcv(symbol=symbol, interval=interval, years=years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.btc.backtest import add_signals
    p = self.getParams(**params)
    return add_signals(data, short=p["short"], long=p["long"])

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.btc.backtest import add_signals, run_backtest, calc_metrics, calc_equity_curve
    p = self.getParams(**params)

    df = add_signals(data, short=p["short"], long=p["long"])
    df, trades, finalValue = run_backtest(
      df, initial_capital=p["capital"], threshold=p["threshold"])
    metricsRaw = calc_metrics(df, trades, p["capital"], finalValue)

    # 共通メトリクスフォーマットに変換
    sellTrades = [t for t in trades if t["type"] == "sell"]
    wins = [t for t in sellTrades if t.get("pnl", 0) > 0]
    equity = calc_equity_curve(df, trades, p["capital"])
    # equityを%→絶対値に戻す
    equityAbs = (equity / 100 + 1) * p["capital"]

    metrics = {
      "totalReturn": (finalValue - p["capital"]) / p["capital"] * 100,
      "finalValue": finalValue,
      "totalTrades": len(sellTrades),
      "winRate": len(wins) / len(sellTrades) * 100 if sellTrades else 0,
      "profitFactor": 0,
      "mdd": float(((equityAbs - equityAbs.cummax()) / equityAbs.cummax() * 100).min()) if len(equityAbs) > 0 else 0,
      "totalFees": 0,
    }

    return BacktestResult(
      strategyName=self.description,
      symbol=params.get("symbol", "BTCUSDT"),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equityAbs,
      metrics=metrics,
      params=p,
    )


register(BtcMaStrategy())
