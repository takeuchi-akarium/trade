"""
ロングショートポートフォリオ構築・実績トラッキング

シグナル上位q%をロング、下位q%をショート (等ウェイト)。
ポジション履歴をJSONに保存し、実績を追跡する。
"""

import json
import math
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from leadlag.constants import JP_TICKERS, JP_SECTOR_NAMES, QUANTILE_CUTOFF


def constructPortfolioWithRegime(signals, jpOcReturns, q=QUANTILE_CUTOFF, regimeWindow=20):
  """
  レジーム検知付きポートフォリオ構築。

  直近regimeWindow日の戦略的中率に応じてポジションサイズを調整。
  的中率が高い → フルポジション、的中率が低い → ポジション縮小。

  Args:
    signals: DataFrame (日付 x JP銘柄) の予測シグナル
    jpOcReturns: DataFrame (日付 x JP銘柄) の実現OCリターン
    q: 上下の分位点
    regimeWindow: 的中率計算のウィンドウ (営業日)

  Returns:
    DataFrame: 日次ポートフォリオリターン (レジーム調整済み)
  """
  commonDates = signals.index.intersection(jpOcReturns.index)
  tickers = [t for t in JP_TICKERS if t in signals.columns and t in jpOcReturns.columns]
  nLong = max(1, math.ceil(len(tickers) * q))

  # まず全期間の生リターンを計算
  rawResults = []
  for date in commonDates:
    sig = signals.loc[date, tickers].dropna()
    if len(sig) < nLong * 2:
      continue

    ranked = sig.sort_values(ascending=False)
    longTickers = ranked.index[:nLong].tolist()
    shortTickers = ranked.index[-nLong:].tolist()

    actualRet = jpOcReturns.loc[date, tickers]
    longRet = actualRet[longTickers].mean()
    shortRet = actualRet[shortTickers].mean()
    portRet = longRet - shortRet

    # シグナル強度: 上位と下位の平均シグナル差
    sigStrength = ranked.iloc[:nLong].mean() - ranked.iloc[-nLong:].mean()

    rawResults.append({
      "Date": date,
      "port_return": portRet,
      "long_return": longRet,
      "short_return": shortRet,
      "long_tickers": longTickers,
      "short_tickers": shortTickers,
      "sig_strength": sigStrength,
    })

  rawDf = pd.DataFrame(rawResults).set_index("Date")
  if len(rawDf) == 0:
    return rawDf

  # レジーム判定: 直近の的中率とシグナル強度で調整
  adjResults = []
  for i in range(len(rawDf)):
    row = rawDf.iloc[i]
    date = rawDf.index[i]

    if i < regimeWindow:
      # ウォームアップ期間はフルポジション
      confidence = 1.0
    else:
      recentRet = rawDf["port_return"].iloc[i - regimeWindow:i]
      hitRate = (recentRet > 0).mean()

      # 的中率50%を基準に、55%以上でフル、45%以下でゼロ
      confidence = np.clip((hitRate - 0.45) / 0.10, 0.0, 1.0)

    adjReturn = row["port_return"] * confidence

    adjResults.append({
      "Date": date,
      "port_return": adjReturn,
      "long_return": row["long_return"] * confidence,
      "short_return": row["short_return"] * confidence,
      "long_tickers": row["long_tickers"],
      "short_tickers": row["short_tickers"],
      "confidence": confidence,
    })

  return pd.DataFrame(adjResults).set_index("Date")


def constructPortfolio(signals, jpOcReturns, q=QUANTILE_CUTOFF):
  """
  シグナルに基づくロングショートポートフォリオを構築 (論文 式3-7)。

  Args:
    signals: DataFrame (日付 x JP銘柄) の予測シグナル
    jpOcReturns: DataFrame (日付 x JP銘柄) の実現OCリターン
    q: 上下の分位点 (0.3 = 上位/下位30%)

  Returns:
    DataFrame: 日次ポートフォリオリターンと構成銘柄
  """
  commonDates = signals.index.intersection(jpOcReturns.index)
  tickers = [t for t in JP_TICKERS if t in signals.columns and t in jpOcReturns.columns]
  nLong = max(1, math.ceil(len(tickers) * q))

  results = []
  for date in commonDates:
    sig = signals.loc[date, tickers].dropna()
    if len(sig) < nLong * 2:
      continue

    ranked = sig.sort_values(ascending=False)
    longTickers = ranked.index[:nLong].tolist()
    shortTickers = ranked.index[-nLong:].tolist()

    # 等ウェイトリターン (式5-7)
    actualRet = jpOcReturns.loc[date, tickers]
    longRet = actualRet[longTickers].mean()
    shortRet = actualRet[shortTickers].mean()
    portRet = longRet - shortRet

    results.append({
      "Date": date,
      "port_return": portRet,
      "long_return": longRet,
      "short_return": shortRet,
      "long_tickers": longTickers,
      "short_tickers": shortTickers,
    })

  return pd.DataFrame(results).set_index("Date")


def selectPositions(todaySignal, q=QUANTILE_CUTOFF):
  """
  本日のシグナルからロング/ショート銘柄を選定 (バッチ用)。

  Returns:
    dict: {
      "long": [{"ticker": ..., "name": ..., "score": ...}, ...],
      "short": [...],
    }
  """
  signals = todaySignal["signals"]
  jpReturns = todaySignal.get("jpReturns", {})
  ranked = sorted(signals.items(), key=lambda x: x[1], reverse=True)
  nLong = max(1, math.ceil(len(ranked) * q))

  def buildPos(ticker, score):
    pos = {"ticker": ticker, "name": JP_SECTOR_NAMES.get(ticker, ticker), "score": round(score, 4)}
    ret = jpReturns.get(ticker)
    if ret is not None and not (isinstance(ret, float) and math.isnan(ret)):
      pos["prevReturn"] = round(ret * 100, 2)
    return pos

  longPos = [buildPos(t, s) for t, s in ranked[:nLong]]
  shortPos = [buildPos(t, s) for t, s in ranked[-nLong:]]

  return {"long": longPos, "short": shortPos}


def recordPosition(positions, date, outputPath, confidence=None):
  """ポジション履歴をJSONに追記"""
  outputPath = Path(outputPath)
  outputPath.parent.mkdir(parents=True, exist_ok=True)

  history = []
  if outputPath.exists():
    with open(outputPath, "r", encoding="utf-8") as f:
      history = json.load(f)

  entry = {
    "date": str(date),
    "timestamp": datetime.now().isoformat(),
    "long": positions["long"],
    "short": positions["short"],
  }
  if confidence is not None:
    entry["confidence"] = round(confidence, 2)
  history.append(entry)

  with open(outputPath, "w", encoding="utf-8") as f:
    json.dump(history, f, ensure_ascii=False, indent=2)
