"""
確信度指標の有効性検証

3つの候補指標について、値が高い日 vs 低い日で
ポートフォリオリターンに有意な差があるか検証する。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import math
import numpy as np
import pandas as pd

from leadlag.constants import (
  US_TICKERS, JP_TICKERS, N_US, N_JP,
  ROLLING_WINDOW, LAMBDA_REG, NUM_FACTORS, QUANTILE_CUTOFF,
  C_FULL_START, C_FULL_END, buildPriorSubspace,
)
from leadlag.subspace_pca import (
  buildPriorExposure, estimateCorrelation, subspaceRegPca, projectSignal,
)
from leadlag.fetch_data import fetchAllPrices, calcCcReturns, calcOcReturns
from leadlag.calendar_align import alignReturns
from leadlag.signal_generator import _prepareModel, _rankNormalize


def generateSignalsWithMeta(aligned, lam=LAMBDA_REG, k=NUM_FACTORS, window=ROLLING_WINDOW,
                            beta=0.2, momWindow=5):
  """シグナル + 確信度メタ情報を同時に生成"""
  c0, allCols, usCols, jpCols = _prepareModel(aligned)
  validData = aligned[allCols]

  # JP モメンタム
  jpCcCols = [f"jp_cc_{t}" for t in JP_TICKERS]
  jpCcAvail = [c for c in jpCcCols if c in aligned.columns]
  jpCcData = aligned[jpCcAvail].rename(columns=lambda c: c.replace("jp_cc_", ""))
  jpMom = jpCcData.rolling(momWindow).mean()

  nLong = max(1, math.ceil(len(JP_TICKERS) * QUANTILE_CUTOFF))
  results = []

  for i in range(window, len(validData)):
    windowData = validData.iloc[i - window:i].values
    cSample, mu, sigma = estimateCorrelation(windowData)
    loadingsUs, loadingsJp, _ = subspaceRegPca(cSample, c0, lam, k)

    currentRow = validData.iloc[i]
    usRaw = currentRow[usCols].values.astype(float)
    if np.any(np.isnan(usRaw)):
      continue

    usMu = mu[:N_US]
    usSigma = sigma[:N_US]
    usShock = (usRaw - usMu) / usSigma
    jpPredicted, factorScores = projectSignal(usShock, loadingsUs, loadingsJp)

    date = validData.index[i]

    # Enhanced signal (PCA + MOM blend)
    momVals = jpMom.loc[date, JP_TICKERS].values.astype(float) if date in jpMom.index else None
    if momVals is not None and not np.any(np.isnan(momVals)):
      pcaRank = _rankNormalize(jpPredicted)
      momRank = _rankNormalize(momVals)
      enhanced = (1 - beta) * pcaRank + beta * momRank
    else:
      enhanced = jpPredicted

    # 確信度指標
    ranked = np.sort(enhanced)[::-1]
    sigSpread = np.mean(ranked[:nLong]) - np.mean(ranked[-nLong:])
    factorAbsSum = np.sum(np.abs(factorScores))
    usAbsSum = np.sum(np.abs(usRaw))

    results.append({
      "Date": date,
      "sigSpread": sigSpread,
      "factorAbsSum": factorAbsSum,
      "usAbsSum": usAbsSum,
      **dict(zip(JP_TICKERS, enhanced)),
    })

  df = pd.DataFrame(results).set_index("Date")
  meta = df[["sigSpread", "factorAbsSum", "usAbsSum"]]
  signals = df[[t for t in JP_TICKERS if t in df.columns]]
  return signals, meta


def evaluate(portReturn, meta, indicatorName, backtestStart="2015-01-01"):
  """指標の上位/下位半分でリターンを比較"""
  common = portReturn.index.intersection(meta.index)
  common = common[common >= backtestStart]
  ret = portReturn.loc[common]
  ind = meta.loc[common, indicatorName]

  median = ind.median()
  highMask = ind >= median
  lowMask = ind < median

  highRet = ret[highMask]
  lowRet = ret[lowMask]

  def stats(r):
    ar = np.mean(r) * 245 * 100
    risk = np.std(r, ddof=1) * np.sqrt(245) * 100
    rr = ar / risk if risk > 0 else 0
    hitRate = np.mean(r > 0) * 100
    return ar, risk, rr, hitRate

  hAr, hRisk, hRr, hHit = stats(highRet)
  lAr, lRisk, lRr, lHit = stats(lowRet)

  print(f"\n--- {indicatorName} ---")
  print(f"  中央値: {median:.4f}")
  print(f"  {'':12s} {'AR%':>8s} {'RISK%':>8s} {'R/R':>8s} {'勝率%':>8s} {'日数':>6s}")
  print(f"  {'高い日':12s} {hAr:>8.2f} {hRisk:>8.2f} {hRr:>8.2f} {hHit:>8.1f} {len(highRet):>6d}")
  print(f"  {'低い日':12s} {lAr:>8.2f} {lRisk:>8.2f} {lRr:>8.2f} {lHit:>8.1f} {len(lowRet):>6d}")
  print(f"  {'差':12s} {hAr-lAr:>8.2f} {'':>8s} {hRr-lRr:>8.2f} {hHit-lHit:>8.1f}")

  return hRr, lRr


def main():
  print("=== 確信度指標の有効性検証 ===\n")

  print("[1/4] データ取得中...")
  usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end="2025-12-31")
  usRetCc = calcCcReturns(usPrices, US_TICKERS)
  jpRetCc = calcCcReturns(jpPrices, JP_TICKERS)
  jpRetOc = calcOcReturns(jpPrices, JP_TICKERS)
  aligned = alignReturns(usRetCc, jpRetCc, jpRetOc)

  print("[2/4] シグナル + メタ情報生成中...")
  signals, meta = generateSignalsWithMeta(aligned)

  print("[3/4] ポートフォリオ構築中...")
  from leadlag.portfolio import constructPortfolio
  jpOcCols = {f"jp_oc_{t}": t for t in JP_TICKERS}
  jpOcAligned = aligned[[c for c in jpOcCols if c in aligned.columns]].rename(columns=jpOcCols)
  portfolio = constructPortfolio(signals, jpOcAligned)

  print("[4/4] 指標別リターン比較\n")
  for ind in ["sigSpread", "factorAbsSum", "usAbsSum"]:
    evaluate(portfolio["port_return"], meta, ind)

  # 複合指標: 3つを正規化して合算
  print("\n--- 複合スコア (3指標合算) ---")
  normalized = meta.copy()
  for col in normalized.columns:
    s = normalized[col]
    normalized[col] = (s - s.mean()) / s.std()
  meta["composite"] = normalized.sum(axis=1)
  evaluate(portfolio["port_return"], meta, "composite")


if __name__ == "__main__":
  main()
