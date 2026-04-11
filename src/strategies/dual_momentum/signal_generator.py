"""
デュアルモメンタム シグナル生成

毎月末に以下を判定:
  1. 相対モメンタム: SPY vs EFA の過去12ヶ月リターンで強い方を選択
  2. 絶対モメンタム: 選んだ方が BIL (Tビル) より強ければ投資、弱ければ AGG (債券) に退避
"""

import pandas as pd
import numpy as np

from dual_momentum.constants import (
  EQUITY_US, EQUITY_INTL, BOND, TBILL,
  LOOKBACK_MONTHS, TICKER_NAMES,
)


def calcMomentum(prices, months=LOOKBACK_MONTHS):
  """各ETFの N ヶ月モメンタム (リターン) を計算"""
  return prices.pct_change(months)


def generateSignals(prices, lookback=LOOKBACK_MONTHS):
  """
  月次シグナルを生成。

  Args:
    prices: DataFrame (月末終値, columns=[SPY, EFA, AGG, BIL])
    lookback: ルックバック期間 (月)

  Returns:
    DataFrame: index=月末日付, columns=[signal, momentum_us, momentum_intl, momentum_tbill, chosen]
  """
  momentum = calcMomentum(prices, lookback)

  records = []
  for i in range(lookback, len(prices)):
    date = prices.index[i]
    momUs = momentum[EQUITY_US].iloc[i]
    momIntl = momentum[EQUITY_INTL].iloc[i]
    momTbill = momentum[TBILL].iloc[i]

    # 1. 相対モメンタム: SPY vs EFA
    if momUs >= momIntl:
      chosen = EQUITY_US
      chosenMom = momUs
    else:
      chosen = EQUITY_INTL
      chosenMom = momIntl

    # 2. 絶対モメンタム: chosen vs Tビル
    if chosenMom > momTbill:
      signal = chosen
    else:
      signal = BOND

    records.append({
      "date": date,
      "signal": signal,
      "chosen_equity": chosen,
      "momentum_us": round(momUs * 100, 2),
      "momentum_intl": round(momIntl * 100, 2),
      "momentum_tbill": round(momTbill * 100, 2),
    })

  return pd.DataFrame(records).set_index("date")


def generateTodaySignal(prices, lookback=LOOKBACK_MONTHS):
  """
  最新月のシグナルを返す。

  Returns:
    dict: {date, signal, signal_name, chosen_equity, momentum_us, momentum_intl, momentum_tbill}
  """
  signals = generateSignals(prices, lookback)
  if signals.empty:
    return None

  latest = signals.iloc[-1]
  return {
    "date": str(latest.name.date()),
    "signal": latest["signal"],
    "signal_name": TICKER_NAMES.get(latest["signal"], latest["signal"]),
    "chosen_equity": latest["chosen_equity"],
    "chosen_equity_name": TICKER_NAMES.get(latest["chosen_equity"], latest["chosen_equity"]),
    "momentum_us": latest["momentum_us"],
    "momentum_intl": latest["momentum_intl"],
    "momentum_tbill": latest["momentum_tbill"],
  }
