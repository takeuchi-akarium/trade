"""
DART戦略 (Dynamic Adaptive Regime Trading)

SMA50乖離率の強度に応じて参加戦略数を動的に変える「段階制」で運用。
bb, ema_don, bb_ls の3サブ戦略をレジームに応じて配分する。

レジストリに登録することで bench から他戦略と同列に評価できる。
"""

import pandas as pd
import numpy as np

from strategies.base import Strategy, BacktestResult
from strategies.registry import register


# scenario.py と設定を共有（二重定義を避ける）
from simulator.scenario import ALLOCATION_PATTERNS

GRADIENT_LEVELS = ALLOCATION_PATTERNS["gradient"]["levels"]
NAN_DEFAULT = ALLOCATION_PATTERNS["gradient"].get("nanDefault", (0.70, 0.30, 0.00))
HYSTERESIS = ALLOCATION_PATTERNS["gradient"].get("hysteresis", 1)
TREND_MA_PERIOD = 50

# threshold降順にソート（None は末尾）
SORTED_LEVELS = sorted(
  GRADIENT_LEVELS.items(),
  key=lambda x: x[1]["threshold"] if x[1]["threshold"] is not None else float("-inf"),
  reverse=True,
)


def _gradientWeights(close: float, trendMa: float) -> tuple:
  """乖離率に応じて段階的にweightを返す"""
  if np.isnan(trendMa) or trendMa == 0:
    return NAN_DEFAULT
  dev = (close - trendMa) / trendMa * 100
  for _, info in SORTED_LEVELS:
    if info["threshold"] is not None and dev > info["threshold"]:
      return info["weights"]
  return SORTED_LEVELS[-1][1]["weights"]


class DartStrategy(Strategy):
  name = "dart"
  description = "DART段階制 (bb+ema_don+bb_ls 動的配分)"
  category = "composite"
  version = "2.2.0"
  changelog = [
    {"version": "2.2.0", "date": "2026-04-14", "changes": [
      "シナリオ探索で最適化: 加重平均リターン+27%→+44.7%, 最悪ケース-38%→-16.3%",
      "閾値調整: ±4%→±3% (range帯を狭めてuptrend判定を早める)",
      "range帯: bb70%/ema_don30% (レンジではbb逆張りを主力に)",
      "uptrend帯: bb30%/ema_don70% (トレンド時もbbで安定性確保)",
      "downtrend帯: bb50% (押し目拾いの比率を引き上げ)",
      "ヒステリシス4日 (リバランスを62回に削減)",
    ]},
    {"version": "2.1.0", "date": "2026-04-14", "changes": [
      "閾値拡大: ±2%→±4% (ema_don配分時間を増やす)",
      "bb_lsを廃止→下落時は現金待機 or bb押し目のみ",
      "range帯のema_don配分を10%→50%に引き上げ",
      "ヒステリシス3日導入（リバランス頻度を大幅削減）",
    ]},
    {"version": "2.0.0", "date": "2026-04-14", "changes": [
      "レジーム判定にshift(1)適用: 前日終値+前日SMA50で判定（look-ahead bias修正）",
      "サブ戦略の約定を翌足始値(open)に変更（同一足close約定を廃止）",
      "SL/TPを日中安値(low)/高値(high)で判定（closeのみの判定を廃止）",
    ]},
    {"version": "1.0.0", "date": "2026-04-01", "changes": ["初版"]},
  ]
  defaultParams = {
    "capital": 100_000,
    "fee": 0.1,
    "sl": 5.0,
  }

  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    from strategies.registry import getStrategy
    # bbと同じデータソースを使う
    return getStrategy("bb").fetchData(symbol=symbol, interval=interval, **kwargs)

  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    # DARTはシグナル単体ではなくポートフォリオ運用のため、
    # レジーム判定結果を signal 列に格納する
    # shift(1): 前日までのデータでレジーム判定
    trendMa = data["close"].rolling(TREND_MA_PERIOD).mean().shift(1)
    prevClose = data["close"].shift(1)
    signals = []
    prevWeights = None
    candidateWeights = None
    candidateCount = 0
    for i in range(len(data)):
      close = prevClose.iloc[i] if not pd.isna(prevClose.iloc[i]) else data["close"].iloc[i]
      ma = trendMa.iloc[i]
      rawWeights = _gradientWeights(close, ma)
      # ヒステリシス適用
      if prevWeights is None:
        curWeights = rawWeights
      elif rawWeights == prevWeights:
        curWeights = prevWeights
        candidateWeights = None
        candidateCount = 0
      elif rawWeights == candidateWeights:
        candidateCount += 1
        if candidateCount >= HYSTERESIS:
          curWeights = rawWeights
          candidateWeights = None
          candidateCount = 0
        else:
          curWeights = prevWeights
      else:
        candidateWeights = rawWeights
        candidateCount = 1
        curWeights = prevWeights
      prevWeights = curWeights
      wBb, wEma, wBbLs = curWeights
      # 合計weight > 0 なら参加（1）、全退避なら 0
      signals.append(1 if (wBb + wEma + wBbLs) > 0 else 0)
    data = data.copy()
    data["signal"] = signals
    return data

  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    from strategies.registry import getStrategy
    from strategies.scalping.backtest import runBacktest, runBacktestLongShort

    p = self.getParams(**params)
    capital = p.get("capital", 100_000)
    feePct = p.get("fee", 0.1)
    slPct = p.get("sl", 5.0)

    # 3サブ戦略のシグナル生成+バックテスト
    bbStrategy = getStrategy("bb")
    emaStrategy = getStrategy("ema_don")
    bbLsStrategy = getStrategy("bb_ls")

    dfBb = bbStrategy.generateSignals(data.copy())
    dfEma = emaStrategy.generateSignals(data.copy(), short=10, long=50)
    dfBbLs = bbLsStrategy.generateSignals(data.copy())

    # shift(1): 前日までのデータでレジーム判定（look-ahead bias防止）
    trendMa = data["close"].rolling(TREND_MA_PERIOD).mean().shift(1)

    _, eqBb = runBacktest(dfBb, capital, feePct)
    _, eqEma = runBacktest(dfEma, capital, feePct)
    _, eqBbLs = runBacktestLongShort(dfBbLs, capital, feePct, stopLossPct=slPct)

    retBb = eqBb.pct_change().fillna(0)
    retEma = eqEma.pct_change().fillna(0)
    retBbLs = eqBbLs.pct_change().fillna(0)

    # 段階制でequityを構築（ヒステリシス付き）
    equity = capital
    equityList = []
    prevWeights = None
    candidateWeights = None
    candidateCount = 0
    trades = []

    # 前日の終値でレジーム判定（当日のリターンに適用）
    prevClose = data["close"].shift(1)
    for i in range(len(data)):
      close = prevClose.iloc[i] if not np.isnan(prevClose.iloc[i]) else data["close"].iloc[i]
      ma = trendMa.iloc[i]
      rawWeights = _gradientWeights(close, ma)

      # ヒステリシス: N日連続で同じweightが示されたら遷移
      if prevWeights is None:
        curWeights = rawWeights
      elif rawWeights == prevWeights:
        curWeights = prevWeights
        candidateWeights = None
        candidateCount = 0
      elif rawWeights == candidateWeights:
        candidateCount += 1
        if candidateCount >= HYSTERESIS:
          curWeights = rawWeights
          candidateWeights = None
          candidateCount = 0
        else:
          curWeights = prevWeights
      else:
        candidateWeights = rawWeights
        candidateCount = 1
        curWeights = prevWeights

      wBb, wEma, wBbLs = curWeights

      # リバランスコスト
      if prevWeights is not None and curWeights != prevWeights:
        weightDelta = sum(abs(a - b) for a, b in zip(curWeights, prevWeights))
        rebalanceCost = equity * feePct / 100 * weightDelta
        equity -= rebalanceCost
        trades.append({
          "datetime": data.index[i],
          "type": "rebalance",
          "price": close,
          "weights": curWeights,
        })
      prevWeights = curWeights

      rBb = retBb.iloc[i] if i < len(retBb) else 0
      rEma = retEma.iloc[i] if i < len(retEma) else 0
      rBbLs = retBbLs.iloc[i] if i < len(retBbLs) else 0
      portfolioReturn = wBb * rBb + wEma * rEma + wBbLs * rBbLs

      equity *= (1 + portfolioReturn)
      equityList.append(equity)

    eqSeries = pd.Series(equityList, index=data.index)

    # メトリクス
    finalValue = equityList[-1] if equityList else capital
    totalReturn = (finalValue - capital) / capital * 100
    peak = eqSeries.expanding().max()
    dd = (eqSeries - peak) / peak * 100
    mdd = float(dd.min())

    days = (data.index[-1] - data.index[0]).days if len(data) > 1 else 1
    annualReturn = ((finalValue / capital) ** (365.0 / max(days, 1)) - 1) * 100 if days > 0 else 0

    returns = eqSeries.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 0 and returns.std() > 0 else 0

    metrics = {
      "totalReturn": totalReturn,
      "finalValue": finalValue,
      "mdd": mdd,
      "annualReturn": annualReturn,
      "sharpe": round(sharpe, 2),
      "totalTrades": len(trades),
      "winRate": 0,  # リバランス型のため勝率は非該当
      "profitFactor": 0,
    }

    return BacktestResult(
      strategyName=self.name,
      symbol=params.get("symbol", "BTCUSDT"),
      interval=params.get("interval", "1d"),
      trades=trades,
      equity=eqSeries,
      metrics=metrics,
      params=p,
    )


register(DartStrategy())
