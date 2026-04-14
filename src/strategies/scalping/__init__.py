"""
短期売買戦略 (RSI, BB, EMA, VWAP)

各テクニカル指標を個別の Strategy として登録する。
"""

import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


# Binance / yfinance の判定とデータ取得は既存の run.py から流用
BINANCE_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"}


def _isBinance(symbol: str) -> bool:
  return symbol.upper() in BINANCE_SYMBOLS or symbol.upper().endswith("USDT")


def _fetchData(symbol: str, interval: str = "1d", years: int = 1) -> pd.DataFrame:
  if _isBinance(symbol):
    from strategies.btc.fetch_btc import fetch_ohlcv
    return fetch_ohlcv(symbol=symbol.upper(), interval=interval, years=years)
  else:
    import yfinance as yf
    periodMap = {1: "1y", 2: "2y", 3: "5y", 5: "5y"}
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


def _runBacktest(df, initialCapital, feePct, slPct, tpPct):
  """既存のバックテストエンジンをそのまま使う"""
  from strategies.scalping.backtest import runBacktest, calcMetrics
  trades, equity = runBacktest(df, initialCapital, feePct, slPct, tpPct)
  metrics = calcMetrics(trades, equity, initialCapital)
  return trades, equity, metrics


def _runBacktestLS(df, initialCapital, feePct, slPct, tpPct):
  """ロング/ショート両対応バックテスト"""
  from strategies.scalping.backtest import runBacktestLongShort, calcMetrics
  trades, equity = runBacktestLongShort(df, initialCapital, feePct, slPct, tpPct)
  metrics = calcMetrics(trades, equity, initialCapital)
  return trades, equity, metrics


class ScalpingStrategy(Strategy):
  """テクニカル指標ベースの短期売買戦略"""

  version = "2.0.0"
  changelog = [
    {"version": "2.0.0", "date": "2026-04-14", "changes": [
      "約定を翌足始値(open)に変更（同一足close約定を廃止、look-ahead bias修正）",
      "SL/TPを日中安値(low)/高値(high)で判定（closeのみの判定を廃止）",
    ]},
    {"version": "1.0.0", "date": "2026-04-01", "changes": ["初版"]},
  ]

  def __init__(self, key: str, name: str, defaults: dict):
    self.name = key
    self.description = name
    self.category = "short_term"
    self.defaultParams = {
      "capital": 100_000,
      "fee": 0.1,
      "sl": None,
      "tp": None,
      **defaults,
    }
    self._key = key

  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    years = kwargs.get("years", 1)
    return _fetchData(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.scalping.strategies import calcSignals
    p = self.getParams(**params)
    # 共通パラメータを除外し、戦略固有のパラメータのみ渡す
    from strategies.scalping.strategies import STRATEGIES as _S
    validKeys = set(_S[self._key]["defaults"].keys())
    strategyParams = {k: v for k, v in p.items() if k in validKeys}
    return calcSignals(data, self._key, **strategyParams)

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    p = self.getParams(**params)
    dfS = self.generateSignals(data, **params)
    trades, equity, metrics = _runBacktest(
      dfS, p["capital"], p["fee"], p.get("sl"), p.get("tp"))
    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


class ScalpingStrategyLS(Strategy):
  """テクニカル指標ベース ロング/ショート両対応"""
  version = "2.0.0"
  changelog = [
    {"version": "2.0.0", "date": "2026-04-14", "changes": [
      "約定を翌足始値(open)に変更（同一足close約定を廃止、look-ahead bias修正）",
      "SL/TPを日中安値(low)/高値(high)で判定（closeのみの判定を廃止）",
    ]},
    {"version": "1.0.0", "date": "2026-04-01", "changes": ["初版"]},
  ]

  def __init__(self, key: str, name: str, defaults: dict):
    self.name = f"{key}_ls"
    self.description = f"{name} (L/S)"
    self.category = "short_term"
    self.defaultParams = {
      "capital": 100_000,
      "fee": 0.1,
      "sl": None,
      "tp": None,
      **defaults,
    }
    self._key = key

    # bb_trend L/SにはデフォルトSLを設定（逆トレンド暴走防止の2次防御）
    if key == "bb_trend" and self.defaultParams.get("sl") is None:
      self.defaultParams["sl"] = 3.0

  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    years = kwargs.get("years", 1)
    return _fetchData(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    from strategies.scalping.strategies import calcSignals, STRATEGIES as _S
    p = self.getParams(**params)
    validKeys = set(_S[self._key]["defaults"].keys())
    strategyParams = {k: v for k, v in p.items() if k in validKeys}
    return calcSignals(data, self._key, **strategyParams)

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    p = self.getParams(**params)
    dfS = self.generateSignals(data, **params)
    trades, equity, metrics = _runBacktestLS(
      dfS, p["capital"], p["fee"], p.get("sl"), p.get("tp"))
    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


# 既存の STRATEGIES レジストリから全戦略を登録
from strategies.scalping.strategies import STRATEGIES as _STRATS

for _key, _entry in _STRATS.items():
  register(ScalpingStrategy(_key, _entry["name"], _entry["defaults"]))
  register(ScalpingStrategyLS(_key, _entry["name"], _entry["defaults"]))
