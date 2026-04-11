"""
共通メトリクス算出

BacktestResult の metrics が不足している場合に
trades / equity から共通メトリクスを補完する。
"""

import numpy as np
import pandas as pd


def ensureMetrics(metrics: dict, trades: list[dict], equity: pd.Series, initialCapital: float = 100_000) -> dict:
  """metricsに不足しているキーがあれば trades / equity から算出して補完"""
  m = dict(metrics)

  if len(equity) == 0:
    return m

  finalValue = equity.iloc[-1]

  if "totalReturn" not in m:
    m["totalReturn"] = (finalValue - initialCapital) / initialCapital * 100

  if "finalValue" not in m:
    m["finalValue"] = finalValue

  if "mdd" not in m:
    peak = equity.cummax()
    dd = (equity - peak) / peak * 100
    m["mdd"] = float(dd.min())

  if "annualReturn" not in m and len(equity) > 1:
    days = (equity.index[-1] - equity.index[0]).days
    if days > 0:
      totalRet = finalValue / initialCapital
      m["annualReturn"] = (totalRet ** (365.0 / days) - 1) * 100

  if "sharpe" not in m and len(equity) > 1:
    returns = equity.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
      m["sharpe"] = round(returns.mean() / returns.std() * np.sqrt(252), 2)

  # 月別パフォーマンスを生成
  if "monthlyStats" not in m:
    m["monthlyStats"] = _calcMonthlyFromEquity(equity)

  return m


def _calcMonthlyFromEquity(equity: pd.Series) -> list[dict]:
  """equity curveから月別リターンを算出"""
  if len(equity) < 2:
    return []

  monthly = equity.resample("ME").last().dropna()
  if len(monthly) < 2:
    return []

  returns = monthly.pct_change().dropna()
  result = []
  for date, ret in returns.items():
    result.append({
      "month": date.strftime("%Y-%m"),
      "return": round(ret * 100, 2),
    })
  return result
