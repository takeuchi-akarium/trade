"""
日米リードラグ・シグナル生成

ウォークフォワードで各営業日のシグナルを生成する。
全期間(バックテスト用) と 本日分のみ(バッチ用) の2つのモードを提供。
"""

import math
import numpy as np
import pandas as pd

from leadlag.constants import (
  US_TICKERS, JP_TICKERS, N_US, N_JP,
  ROLLING_WINDOW, LAMBDA_REG, NUM_FACTORS,
  C_FULL_START, C_FULL_END, buildPriorSubspace,
)
from leadlag.subspace_pca import (
  buildPriorExposure, estimateCorrelation, subspaceRegPca, projectSignal,
)


def _prepareModel(aligned):
  """事前部分空間とC0を構築"""
  v0 = buildPriorSubspace()

  # C_full: 長期サンプルから推定
  fullMask = (aligned.index >= C_FULL_START) & (aligned.index <= C_FULL_END)
  fullData = aligned.loc[fullMask]

  usCols = [f"us_cc_{t}" for t in US_TICKERS]
  jpCols = [f"jp_cc_{t}" for t in JP_TICKERS]
  allCols = usCols + jpCols

  fullReturns = fullData[allCols].values  # NaN許容、estimateCorrelation内で処理
  cFull, _, _ = estimateCorrelation(fullReturns)
  c0 = buildPriorExposure(cFull, v0)

  return c0, allCols, usCols, jpCols


def generateSignals(aligned, lam=LAMBDA_REG, k=NUM_FACTORS, window=ROLLING_WINDOW):
  """
  全期間のシグナルを生成 (バックテスト用)。

  Args:
    aligned: alignReturns() の出力
    lam: 正則化パラメータ
    k: ファクター数
    window: ローリングウィンドウ長

  Returns:
    signals: DataFrame (日付 x JP銘柄) の予測シグナル
  """
  c0, allCols, usCols, jpCols = _prepareModel(aligned)
  validData = aligned[allCols]

  results = []
  for i in range(window, len(validData)):
    windowData = validData.iloc[i - window:i].values
    cSample, mu, sigma = estimateCorrelation(windowData)

    loadingsUs, loadingsJp, _ = subspaceRegPca(cSample, c0, lam, k)

    # 当日の米国リターンを標準化
    currentRow = validData.iloc[i]
    usRaw = currentRow[usCols].values.astype(float)

    # US側にNaNがあればスキップ
    if np.any(np.isnan(usRaw)):
      continue

    usMu = mu[:N_US]
    usSigma = sigma[:N_US]
    usShock = (usRaw - usMu) / usSigma

    jpPredicted, _ = projectSignal(usShock, loadingsUs, loadingsJp)
    date = validData.index[i]
    results.append({"Date": date, **dict(zip(JP_TICKERS, jpPredicted))})

  signals = pd.DataFrame(results).set_index("Date")
  return signals


def generateSignalsWithFeedback(
  aligned, lam=LAMBDA_REG, k=NUM_FACTORS, window=ROLLING_WINDOW,
  alpha=0.5, fbWindow=5,
):
  """
  予測誤差フィードバック付きシグナル生成。

  直近fbWindow日間の予測残差 (実現CC - 予測) のクロスセクション順位を
  シグナルのランキング調整に使う。

  考え方:
  - 基本シグナル: PCAベースの予測値（ランキング用）
  - 残差項: 直近の「予測より強かった/弱かった」銘柄の傾向
  - 両者をランキングベースでブレンドし、ノイズを抑制

  Args:
    aligned: alignReturns() の出力
    lam, k, window: PCAパラメータ
    alpha: フィードバック強度 (0=PCAのみ, 1=残差のみ)
    fbWindow: 残差の移動平均窓 (営業日)

  Returns:
    signals: DataFrame (日付 x JP銘柄) の調整済みシグナル
  """
  c0, allCols, usCols, jpCols = _prepareModel(aligned)
  validData = aligned[allCols]

  # 実現リターン (JP CC)
  jpCcCols = [f"jp_cc_{t}" for t in JP_TICKERS]
  jpCcAvail = [c for c in jpCcCols if c in aligned.columns]
  jpCcData = aligned[jpCcAvail].rename(columns=lambda c: c.replace("jp_cc_", ""))

  # まずベースシグナルと残差を全て計算
  baseSignals = []
  residuals = []
  dates = []

  prevPredicted = None
  prevDate = None

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
    jpPredicted, _ = projectSignal(usShock, loadingsUs, loadingsJp)

    date = validData.index[i]
    baseSignals.append(jpPredicted)
    dates.append(date)

    # 前日の残差を記録
    if prevPredicted is not None and prevDate in jpCcData.index:
      actual = jpCcData.loc[prevDate, JP_TICKERS].values.astype(float)
      if not np.any(np.isnan(actual)):
        residuals.append(actual - prevPredicted)
      else:
        residuals.append(np.zeros(N_JP))
    else:
      residuals.append(np.zeros(N_JP))

    prevPredicted = jpPredicted.copy()
    prevDate = date

  # ランキングベースでブレンド
  results = []
  for j in range(len(dates)):
    baseRank = _rankNormalize(baseSignals[j])

    # 直近fbWindow日の残差平均をランキング化
    start = max(0, j - fbWindow + 1)
    recentResiduals = residuals[start:j + 1]
    if len(recentResiduals) > 0 and j > 0:
      avgResidual = np.mean(recentResiduals, axis=0)
      residualRank = _rankNormalize(avgResidual)
    else:
      residualRank = np.zeros(N_JP)

    # ブレンド: (1-alpha) * PCAランク + alpha * 残差ランク
    blended = (1 - alpha) * baseRank + alpha * residualRank
    results.append({"Date": dates[j], **dict(zip(JP_TICKERS, blended))})

  signals = pd.DataFrame(results).set_index("Date")
  return signals


def generateSignalsEnhanced(aligned, lam=LAMBDA_REG, k=NUM_FACTORS, window=ROLLING_WINDOW,
                            beta=0.2, momWindow=5):
  """
  PCA + 日本短期モメンタムのブレンドシグナル。

  日本市場の直近数日のセクター別トレンドをPCAシグナルに
  ランキングベースで混合する。モメンタムが短期的に続く傾向を
  利用して予測精度を向上させる。

  Args:
    aligned: alignReturns() の出力
    lam, k, window: PCAパラメータ
    beta: モメンタムの混合比率 (0=PCAのみ, 1=MOMのみ)
    momWindow: モメンタム計算の日数

  Returns:
    signals: DataFrame (日付 x JP銘柄) の調整済みシグナル
  """
  # PCAベースシグナル
  pcaSig = generateSignals(aligned, lam=lam, k=k, window=window)

  # 日本側モメンタム: 直近momWindow日のCC平均
  jpCcCols = [f"jp_cc_{t}" for t in JP_TICKERS]
  jpCcAvail = [c for c in jpCcCols if c in aligned.columns]
  jpCcData = aligned[jpCcAvail].rename(columns=lambda c: c.replace("jp_cc_", ""))
  jpMom = jpCcData.rolling(momWindow).mean()

  # 共通日付でランクベースブレンド
  commonDates = pcaSig.index.intersection(jpMom.index)
  tickers = [t for t in JP_TICKERS if t in pcaSig.columns and t in jpMom.columns]

  blended = pd.DataFrame(index=commonDates, columns=tickers, dtype=float)
  for d in commonDates:
    pcaVals = pcaSig.loc[d, tickers].values.astype(float)
    momVals = jpMom.loc[d, tickers].values.astype(float)
    if np.any(np.isnan(pcaVals)) or np.any(np.isnan(momVals)):
      blended.loc[d] = pcaVals
      continue
    pcaRank = _rankNormalize(pcaVals)
    momRank = _rankNormalize(momVals)
    blended.loc[d] = (1 - beta) * pcaRank + beta * momRank

  return blended


def _rankNormalize(arr):
  """配列をランキングに変換し、[-1, 1] にスケーリング"""
  n = len(arr)
  if n == 0:
    return arr
  order = np.argsort(np.argsort(arr))  # 0-based rank
  return 2.0 * order / (n - 1) - 1.0 if n > 1 else np.zeros(n)


def generateTodaySignal(aligned, lam=LAMBDA_REG, k=NUM_FACTORS, window=ROLLING_WINDOW,
                        beta=0.2, momWindow=5):
  """
  本日分のシグナルを生成 (バッチ用)。
  PCA + 日本短期モメンタムのブレンド。

  Returns:
    dict: {
      "date": 対象日,
      "signals": {ticker: score},       (Enhanced: PCA+MOM)
      "signalsRaw": {ticker: score},    (PCAのみ)
      "factorScores": [f1, f2, f3],
      "usReturns": {ticker: return},
    }
  """
  c0, allCols, usCols, jpCols = _prepareModel(aligned)
  validData = aligned[allCols]

  if len(validData) < window + 1:
    raise ValueError(f"データ不足: {len(validData)}行 (最低{window + 1}行必要)")

  # PCAシグナル
  windowData = validData.iloc[-(window + 1):-1].values
  cSample, mu, sigma = estimateCorrelation(windowData)
  loadingsUs, loadingsJp, _ = subspaceRegPca(cSample, c0, lam, k)

  latestRow = validData.iloc[-1]
  usRaw = latestRow[usCols].values.astype(float)
  usMu = mu[:N_US]
  usSigma = sigma[:N_US]
  usShock = (usRaw - usMu) / usSigma

  jpPredicted, factorScores = projectSignal(usShock, loadingsUs, loadingsJp)

  # 日本短期モメンタム
  jpCcCols = [f"jp_cc_{t}" for t in JP_TICKERS]
  jpCcAvail = [c for c in jpCcCols if c in aligned.columns]
  jpCcData = aligned[jpCcAvail].rename(columns=lambda c: c.replace("jp_cc_", ""))
  recentJp = jpCcData.iloc[-momWindow:]
  momVals = recentJp[JP_TICKERS].mean().values.astype(float)

  # ランクベースブレンド
  if not np.any(np.isnan(momVals)):
    pcaRank = _rankNormalize(jpPredicted)
    momRank = _rankNormalize(momVals)
    enhanced = (1 - beta) * pcaRank + beta * momRank
  else:
    enhanced = jpPredicted

  # 確信度: シグナル分散 (ロング上位 - ショート下位の平均スコア差)
  nLong = max(1, math.ceil(len(JP_TICKERS) * 0.3))
  ranked = np.sort(enhanced)[::-1]
  sigSpread = float(np.mean(ranked[:nLong]) - np.mean(ranked[-nLong:]))

  return {
    "date": validData.index[-1],
    "signals": dict(zip(JP_TICKERS, enhanced.tolist())),
    "signalsRaw": dict(zip(JP_TICKERS, jpPredicted.tolist())),
    "factorScores": factorScores.tolist(),
    "usReturns": dict(zip(US_TICKERS, usRaw.tolist())),
    "confidence": sigSpread,
  }
