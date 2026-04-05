"""
パフォーマンス評価指標

論文 Section 4.2 の指標を実装:
  AR: 年率リターン (式27)
  RISK: 年率リスク (式28)
  R/R: リスクリターン比 (式29)
  MDD: 最大ドローダウン (式30)
"""

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 245  # 日本市場の年間営業日 (概算)


def calcMetrics(returns):
  """
  戦略リターン系列からパフォーマンス指標を算出。

  Args:
    returns: Series or array of daily returns

  Returns:
    dict: {ar, risk, rr, mdd, hitRate, totalReturn}
  """
  r = np.asarray(returns)
  T = len(r)
  if T == 0:
    return {"ar": 0, "risk": 0, "rr": 0, "mdd": 0, "hitRate": 0, "totalReturn": 0}

  mu = np.mean(r)

  # 年率リターン (式27)
  ar = mu * TRADING_DAYS_PER_YEAR

  # 年率リスク (式28)
  risk = np.std(r, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)

  # リスクリターン比 (式29)
  rr = ar / risk if risk > 0 else 0

  # 最大ドローダウン (式30)
  cumRet = np.cumprod(1 + r)
  peak = np.maximum.accumulate(cumRet)
  dd = cumRet / peak - 1
  mdd = np.min(dd)

  # 勝率
  hitRate = np.mean(r > 0) if T > 0 else 0

  # トータルリターン
  totalReturn = cumRet[-1] - 1 if T > 0 else 0

  return {
    "ar": round(ar * 100, 2),         # %表示
    "risk": round(risk * 100, 2),      # %表示
    "rr": round(rr, 2),
    "mdd": round(mdd * 100, 2),        # %表示 (負の値)
    "hitRate": round(hitRate * 100, 1), # %表示
    "totalReturn": round(totalReturn * 100, 2),
  }


def calcRunningMetrics(returns):
  """
  月次・年初来の実績を計算 (バッチレポート用)。

  Args:
    returns: Series with DatetimeIndex

  Returns:
    dict: {mtd, ytd, lastDay}
  """
  if len(returns) == 0:
    return {"mtd": 0, "ytd": 0, "lastDay": 0}

  today = returns.index[-1]
  lastDay = returns.iloc[-1] * 100  # %

  # 月初来 (MTD)
  monthStart = today.replace(day=1)
  mtdRet = returns[returns.index >= monthStart]
  mtd = (np.prod(1 + mtdRet) - 1) * 100 if len(mtdRet) > 0 else 0

  # 年初来 (YTD)
  yearStart = today.replace(month=1, day=1)
  ytdRet = returns[returns.index >= yearStart]
  ytd = (np.prod(1 + ytdRet) - 1) * 100 if len(ytdRet) > 0 else 0

  return {
    "mtd": round(mtd, 2),
    "ytd": round(ytd, 2),
    "lastDay": round(lastDay, 2),
  }
