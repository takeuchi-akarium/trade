"""
日本小型株戦略

出来高急増ブレイクアウト + BBスクイーズブレイク
"""

import pandas as pd
from strategies.base import Strategy, BacktestResult
from strategies.registry import register


class VolumeBreakoutStrategy(Strategy):
  """出来高急増ブレイクアウト（日本小型株）"""

  name = "volume_breakout"
  description = "出来高急増ブレイクアウト（日本小型株）"
  category = "short_term"
  defaultParams = {
    "capital": 50_000,
    "volMultiple": 2.5,
    "highPeriod": 20,
    "takeProfitPct": 8.0,
    "stopLossPct": 4.0,
    "maxHoldDays": 5,
    "trailingStopPct": 3.0,
    "slippage": 0.3,
    "useMarketFilter": True,
  }

  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    from strategies.jp_stock.data import fetchOhlcv
    years = kwargs.get("years", 3)
    return fetchOhlcv(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    """シグナル列を追加: +1=エントリー条件成立"""
    import numpy as np
    p = self.getParams(**params)
    df = data.copy()
    df["signal"] = 0

    closes = df["close"].values
    volumes = df["volume"].values
    highPeriod = p["highPeriod"]
    volMultiple = p["volMultiple"]

    for i in range(max(highPeriod, 25), len(df)):
      avgVol20 = np.mean(volumes[i - 20:i])
      volOk = volumes[i] >= avgVol20 * volMultiple

      highMax = np.max(closes[i - highPeriod:i])
      highOk = closes[i] >= highMax

      sma5 = np.mean(closes[i - 5:i])
      sma25 = np.mean(closes[i - 25:i])
      trendOk = closes[i] > sma5 and closes[i] > sma25

      if volOk and highOk and trendOk:
        df.iloc[i, df.columns.get_loc("signal")] = 1

    return df

  def _fetchMarketDf(self, p: dict) -> pd.DataFrame | None:
    """市場トレンドフィルター用のTOPIX ETFデータ取得"""
    if not p.get("useMarketFilter", True):
      return None
    try:
      from strategies.jp_stock.data import fetchOhlcv
      return fetchOhlcv("^N225", interval="1d", years=3)
    except Exception:
      return None

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.jp_stock.backtest import runVolumeBreakoutBacktest
    from strategies.scalping.backtest import calcMetrics
    p = self.getParams(**params)
    marketDf = self._fetchMarketDf(p)

    trades, equity = runVolumeBreakoutBacktest(
      data,
      initialCapital=p["capital"],
      volMultiple=p["volMultiple"],
      highPeriod=p["highPeriod"],
      takeProfitPct=p["takeProfitPct"],
      stopLossPct=p["stopLossPct"],
      maxHoldDays=p["maxHoldDays"],
      slippagePct=p["slippage"],
      trailingStopPct=p["trailingStopPct"],
      marketDf=marketDf,
    )
    metrics = calcMetrics(trades, equity, p["capital"])

    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


class BBSqueezeStrategy(Strategy):
  """BBスクイーズブレイク（日本小型株）"""

  name = "bb_squeeze"
  description = "BBスクイーズブレイク（日本小型株）"
  category = "short_term"
  defaultParams = {
    "capital": 50_000,
    "bbPeriod": 20,
    "bbStd": 2.0,
    "squeezePeriod": 60,
    "squeezeThreshold": 1.2,
    "stopLossPct": 5.0,
    "maxHoldDays": 10,
    "trailingStopPct": 3.0,
    "slippage": 0.3,
    "useMarketFilter": True,
  }

  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    from strategies.jp_stock.data import fetchOhlcv
    years = kwargs.get("years", 3)
    return fetchOhlcv(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    """シグナル列を追加: +1=スクイーズブレイク"""
    import numpy as np
    p = self.getParams(**params)
    df = data.copy()
    df["signal"] = 0

    close = df["close"]
    sma = close.rolling(p["bbPeriod"]).mean()
    std = close.rolling(p["bbPeriod"]).std()
    upper = sma + p["bbStd"] * std
    bandwidth = (2 * p["bbStd"] * std) / sma

    bws = bandwidth.values
    uppers = upper.values
    closes = close.values
    squeezePeriod = p["squeezePeriod"]
    squeezeThreshold = p["squeezeThreshold"]

    startIdx = max(squeezePeriod + p["bbPeriod"], 30)
    for i in range(startIdx, len(df)):
      recentBW = np.mean(bws[i - 4:i + 1])
      minBW = np.nanmin(bws[i - squeezePeriod:i + 1])
      if np.isnan(recentBW) or np.isnan(minBW) or minBW == 0:
        continue

      squeezed = recentBW <= minBW * squeezeThreshold
      breakout = closes[i] > uppers[i] if not np.isnan(uppers[i]) else False

      avgVol10 = np.mean(df["volume"].values[i - 10:i])
      volOk = df["volume"].values[i] >= avgVol10 * 1.5

      if squeezed and breakout and volOk:
        df.iloc[i, df.columns.get_loc("signal")] = 1

    return df

  def _fetchMarketDf(self, p: dict) -> pd.DataFrame | None:
    if not p.get("useMarketFilter", True):
      return None
    try:
      from strategies.jp_stock.data import fetchOhlcv
      return fetchOhlcv("^N225", interval="1d", years=3)
    except Exception:
      return None

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.jp_stock.backtest import runBBSqueezeBacktest
    from strategies.scalping.backtest import calcMetrics
    p = self.getParams(**params)
    marketDf = self._fetchMarketDf(p)

    trades, equity = runBBSqueezeBacktest(
      data,
      initialCapital=p["capital"],
      bbPeriod=p["bbPeriod"],
      bbStd=p["bbStd"],
      squeezePeriod=p["squeezePeriod"],
      squeezeThreshold=p["squeezeThreshold"],
      stopLossPct=p["stopLossPct"],
      maxHoldDays=p["maxHoldDays"],
      slippagePct=p["slippage"],
      trailingStopPct=p["trailingStopPct"],
      marketDf=marketDf,
    )
    metrics = calcMetrics(trades, equity, p["capital"])

    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", ""),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=equity,
      metrics=metrics,
      params=p,
    )


class MomentumRankingStrategy(Strategy):
  """モメンタムランキング（日本小型株・S株分散投資）"""

  name = "jp_momentum"
  description = "モメンタムランキング（日本小型株・月次リバランス）"
  category = "short_term"
  defaultParams = {
    "capital": 50_000,
    "lookbackDays": 60,
    "topN": 5,
    "rebalanceDays": 20,
    "slippage": 0.3,
    "useMarketFilter": True,
  }

  def fetchData(self, symbol: str = "", interval: str = "1d", **kwargs) -> pd.DataFrame:
    """複数銘柄のデータをまとめて取得"""
    from strategies.jp_stock.data import fetchOhlcv
    years = kwargs.get("years", 3)
    return fetchOhlcv(symbol, interval, years)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    """モメンタムランキングはポートフォリオ単位なのでダミー"""
    df = data.copy()
    df["signal"] = 0
    return df

  def backtest(self, data: pd.DataFrame = None, **params) -> BacktestResult:
    """
    ポートフォリオバックテスト。
    dataにはDummy or 単一銘柄データを渡す（CLIとの互換性）。
    実際はstocksDataを内部で取得してポートフォリオ全体をバックテストする。
    """
    from strategies.jp_stock.data import fetchOhlcv, getSmallCapUniverse, fetchMultiple
    from strategies.jp_stock.portfolio_backtest import runMomentumRankingBacktest
    import random

    p = self.getParams(**params)

    # 銘柄ユニバース取得
    universe = getSmallCapUniverse()
    random.seed(42)
    sample = random.sample(universe, min(100, len(universe)))
    symbols = [s["symbol"] for s in sample]

    stocksData = fetchMultiple(symbols, interval="1d", years=3)

    marketDf = None
    if p.get("useMarketFilter", True):
      try:
        marketDf = fetchOhlcv("^N225", interval="1d", years=3)
      except Exception:
        pass

    result = runMomentumRankingBacktest(
      stocksData,
      initialCapital=p["capital"],
      lookbackDays=p["lookbackDays"],
      topN=p["topN"],
      rebalanceDays=p["rebalanceDays"],
      slippagePct=p["slippage"],
      marketDf=marketDf,
      broker="sbi",
    )

    return BacktestResult(
      strategyName=self.name,
      symbol="JP_SMALLCAP",
      interval="1d",
      trades=result["trades"],
      equity=result["equity"],
      metrics=result["metrics"],
      params=p,
      metadata={"stockCount": len(stocksData)},
    )


register(VolumeBreakoutStrategy())
register(BBSqueezeStrategy())
register(MomentumRankingStrategy())
