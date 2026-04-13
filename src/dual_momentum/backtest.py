"""
デュアルモメンタム バックテスト

月次シグナルに従い、翌月のリターンで評価する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from dual_momentum.constants import BACKTEST_START, BOND, TICKER_NAMES
from dual_momentum.fetch_data import fetchPrices
from dual_momentum.signal_generator import generateSignals


def runBacktest(prices=None, startDate=BACKTEST_START):
  """
  デュアルモメンタムのバックテストを実行。

  シグナル月の翌月リターンで評価 (月末リバランス想定)。

  Returns:
    dict: {signals, returns, metrics, monthly_returns}
  """
  if prices is None:
    prices = fetchPrices()

  signals = generateSignals(prices)
  signals = signals[signals.index >= startDate]

  # 各ETFの月次リターン
  monthlyReturns = prices.pct_change().shift(-1)  # 翌月リターン

  # シグナルに従ったポートフォリオリターン
  portReturns = []
  for i in range(len(signals) - 1):  # 最終月は翌月リターンなし
    date = signals.index[i]
    asset = signals["signal"].iloc[i]
    ret = monthlyReturns.loc[date, asset] if date in monthlyReturns.index else 0
    if not np.isnan(ret):
      portReturns.append({"date": date, "return": ret, "asset": asset})

  portDf = pd.DataFrame(portReturns).set_index("date")

  # バイアンドホールド (SPY) との比較
  spyReturns = monthlyReturns["SPY"].loc[signals.index[:-1]].dropna()

  metrics = calcMonthlyMetrics(portDf["return"])
  spyMetrics = calcMonthlyMetrics(spyReturns)

  return {
    "signals": signals,
    "returns": portDf,
    "metrics": metrics,
    "spy_metrics": spyMetrics,
  }


def calcMonthlyMetrics(returns):
  """月次リターン系列からパフォーマンス指標を算出"""
  r = np.asarray(returns)
  T = len(r)
  if T == 0:
    return {"ar": 0, "risk": 0, "rr": 0, "mdd": 0, "hitRate": 0, "totalReturn": 0}

  mu = np.mean(r)

  # 年率リターン (月次 → 年率: 12ヶ月複利)
  ar = (1 + mu) ** 12 - 1

  # 年率リスク (月次 → 年率: √12)
  risk = np.std(r, ddof=1) * np.sqrt(12)

  rr = ar / risk if risk > 0 else 0

  # 最大ドローダウン
  cumRet = np.cumprod(1 + r)
  peak = np.maximum.accumulate(cumRet)
  dd = cumRet / peak - 1
  mdd = np.min(dd)

  hitRate = np.mean(r > 0) if T > 0 else 0
  totalReturn = cumRet[-1] - 1 if T > 0 else 0

  return {
    "ar": round(ar * 100, 2),
    "risk": round(risk * 100, 2),
    "rr": round(rr, 2),
    "mdd": round(mdd * 100, 2),
    "hitRate": round(hitRate * 100, 1),
    "totalReturn": round(totalReturn * 100, 2),
  }


def printReport(result):
  """バックテスト結果をコンソール出力"""
  m = result["metrics"]
  sm = result["spy_metrics"]
  signals = result["signals"]

  print("=" * 50)
  print("デュアルモメンタム バックテスト結果")
  print("=" * 50)

  print(f"\n期間: {signals.index[0].date()} ~ {signals.index[-1].date()}")
  print(f"月数: {len(signals)}")

  # アセット配分の内訳
  counts = signals["signal"].value_counts()
  print("\nアセット配分:")
  for asset, count in counts.items():
    name = TICKER_NAMES.get(asset, asset)
    pct = count / len(signals) * 100
    print(f"  {name} ({asset}): {count}ヶ月 ({pct:.0f}%)")

  print(f"\n{'指標':<16} {'デュアルモメンタム':>18} {'SPY B&H':>12}")
  print("-" * 50)
  print(f"{'年率リターン':<14} {m['ar']:>17.2f}% {sm['ar']:>11.2f}%")
  print(f"{'年率リスク':<15} {m['risk']:>17.2f}% {sm['risk']:>11.2f}%")
  print(f"{'リスクリターン比':<12} {m['rr']:>18.2f} {sm['rr']:>12.2f}")
  print(f"{'最大DD':<16} {m['mdd']:>17.2f}% {sm['mdd']:>11.2f}%")
  print(f"{'勝率':<17} {m['hitRate']:>17.1f}% {sm['hitRate']:>11.1f}%")
  print(f"{'累積リターン':<14} {m['totalReturn']:>17.2f}% {sm['totalReturn']:>11.2f}%")


if __name__ == "__main__":
  result = runBacktest()
  printReport(result)
