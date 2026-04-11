"""
ペアトレード戦略 (US100 x US30)

ナスダック買い × ダウ売りのスプレッドを使った平均回帰戦略。
BB方式とEMA方式の2つのバリエーション。
"""

import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


def _fetchPairData(symbol: str, interval: str, years: int) -> pd.DataFrame:
  """yfinanceで2銘柄のデータを取得してスプレッド算出"""
  import yfinance as yf
  from strategies.pair_trading.pair_strategy import calcSpread

  periodMap = {1: "1y", 2: "2y", 3: "5y", 5: "5y"}
  period = periodMap.get(years, f"{years}y")

  # symbolをパースしてペアを決定 (デフォルト: US100 x US30)
  nasdaqTicker = "^IXIC"
  dowTicker = "^DJI"

  dfN = yf.Ticker(nasdaqTicker).history(period=period, interval=interval)
  dfD = yf.Ticker(dowTicker).history(period=period, interval=interval)
  dfN.columns = [c.lower() for c in dfN.columns]
  dfD.columns = [c.lower() for c in dfD.columns]

  return calcSpread(dfN, dfD)


class PairTradingStrategy(Strategy):
  """ペアトレード戦略 (BB or EMA)"""

  def __init__(self, key: str, name: str, defaults: dict):
    self.name = f"pair_{key}"
    self.description = f"ペアトレード {name}"
    self.category = "pair"
    self.defaultParams = {
      "capital": 1_000_000,
      "fee": 0.1,
      "sl": None,
      "tp": None,
      **defaults,
    }
    self._key = key

  def fetchData(self, symbol: str = "US100xUS30", interval: str = "1d", **kwargs) -> pd.DataFrame:
    years = kwargs.get("years", 2)
    return _fetchPairData(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.pair_trading.pair_strategy import calcPairSignals
    p = self.getParams(**params)
    strategyParams = {k: v for k, v in p.items()
                      if k not in ("capital", "fee", "sl", "tp")}
    return calcPairSignals(data, self._key, **strategyParams)

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.pair_trading.pair_backtest import runPairBacktest, calcPairMetrics
    p = self.getParams(**params)
    dfS = self.generateSignals(data, **params)
    trades, equity = runPairBacktest(
      dfS, p["capital"], p["fee"], p.get("sl"), p.get("tp"))
    metrics = calcPairMetrics(trades, equity, p["capital"])

    return BacktestResult(
      strategyName=self.description,
      symbol=params.get("symbol", "US100xUS30"),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


# 既存のペア戦略レジストリから登録
from strategies.pair_trading.pair_strategy import PAIR_STRATEGIES as _PAIR_STRATS

for _key, _entry in _PAIR_STRATS.items():
  register(PairTradingStrategy(_key, _entry["name"], _entry["defaults"]))
