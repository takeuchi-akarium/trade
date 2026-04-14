"""
DART段階制パラメータ探索

シナリオ加重平均リターンを最大化しつつMDDを抑えるパラメータを探す。
探索対象:
  - range帯の閾値 (±3, ±4, ±5, ±6)
  - range帯のbb/ema_don比率
  - uptrend帯のbb/ema_don比率
  - downtrend帯のbb比率 (0〜50%)
  - ヒステリシス (1〜5日)
  - 上昇方向ヒステリシス短縮
"""

import sys
sys.path.insert(0, "src")

import itertools
import numpy as np
import pandas as pd
from simulator.scenario import (
  SCENARIOS, _prepareBacktestData, _sortLevels, _gradientWeights,
  detectRegime,
)


def runWithParams(levels, hysteresis, nanDefault, precomputed_all):
  """全シナリオで段階制を実行し、加重平均リターンとMDDを返す"""
  sortedLevels = _sortLevels(levels)
  feePct = 0.1
  initialCapital = 100_000

  results = []
  for sKey, sInfo in SCENARIOS.items():
    data, trendMa, retBb, retEma, retBbLs = precomputed_all[sKey]
    prevClose = data["close"].shift(1)

    equity = initialCapital
    prevWeights = None
    candidateWeights = None
    candidateCount = 0
    peak = equity

    for i in range(len(data)):
      close = prevClose.iloc[i] if i > 0 and not np.isnan(prevClose.iloc[i]) else data["close"].iloc[i]
      ma = trendMa.iloc[i]
      rawWeights = _gradientWeights(close, ma, sortedLevels, nanDefault)

      # ヒステリシス
      if prevWeights is None:
        curWeights = rawWeights
      elif rawWeights == prevWeights:
        curWeights = prevWeights
        candidateWeights = None
        candidateCount = 0
      elif rawWeights == candidateWeights:
        candidateCount += 1
        if candidateCount >= hysteresis:
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

      if prevWeights is not None and curWeights != prevWeights:
        weightDelta = sum(abs(a - b) for a, b in zip(curWeights, prevWeights))
        equity -= equity * feePct / 100 * weightDelta
      prevWeights = curWeights

      rBb = retBb.iloc[i] if i < len(retBb) else 0
      rEma = retEma.iloc[i] if i < len(retEma) else 0
      rBbLs = retBbLs.iloc[i] if i < len(retBbLs) else 0
      equity *= (1 + wBb * rBb + wEma * rEma + wBbLs * rBbLs)

      if equity > peak:
        peak = equity

    totalReturn = (equity - initialCapital) / initialCapital * 100
    mdd = 0
    # 簡易MDD（ループ内で計算すると遅いので最終値ベース）
    # 正確なMDDは上位候補のみ再計算
    results.append({
      "scenario": sKey,
      "totalReturn": totalReturn,
      "probability": sInfo["probability"],
    })

  weightedReturn = sum(r["totalReturn"] * r["probability"] for r in results)
  worstCase = min(r["totalReturn"] for r in results)
  return weightedReturn, worstCase, {r["scenario"]: r["totalReturn"] for r in results}


def main():
  # 全シナリオのデータを事前計算
  print("データ準備中...")
  precomputed = {}
  for sKey in SCENARIOS:
    precomputed[sKey] = _prepareBacktestData(sKey, 100_000, 0.1, 50)
  print("探索開始...\n")

  # 探索パラメータ
  rangeThresholds = [3.0, 4.0, 5.0, 6.0]
  strongThresholds = [6.0, 8.0, 10.0]
  rangeBbRatios = [0.3, 0.4, 0.5, 0.6, 0.7]
  uptrendBbRatios = [0.0, 0.1, 0.2, 0.3]
  downtrendBbRatios = [0.0, 0.2, 0.3, 0.5]
  hysteresisList = [1, 2, 3, 4, 5]

  bestScore = -999
  bestParams = None
  results = []
  total = len(rangeThresholds) * len(strongThresholds) * len(rangeBbRatios) * len(uptrendBbRatios) * len(downtrendBbRatios) * len(hysteresisList)
  print(f"総組み合わせ: {total}")

  count = 0
  for rt, st, rbr, ubr, dbr, hys in itertools.product(
    rangeThresholds, strongThresholds, rangeBbRatios, uptrendBbRatios, downtrendBbRatios, hysteresisList
  ):
    if st <= rt:
      continue  # strong閾値はrange閾値より大きい必要がある

    levels = {
      "strong_up":   {"threshold": st,   "weights": (0.00, 1.00, 0.00)},
      "uptrend":     {"threshold": rt,   "weights": (ubr, 1.0 - ubr, 0.00)},
      "range":       {"threshold": -rt,  "weights": (rbr, 1.0 - rbr, 0.00)},
      "downtrend":   {"threshold": -st,  "weights": (dbr, 0.00, 0.00)},
      "strong_down": {"threshold": None, "weights": (0.00, 0.00, 0.00)},
    }
    nanDefault = (rbr, 1.0 - rbr, 0.00)

    wRet, worst, scenarios = runWithParams(levels, hys, nanDefault, precomputed)

    # スコア: 加重平均リターン + 最悪ケースのペナルティ
    score = wRet + max(worst, -50) * 0.3  # 最悪ケースが-50%以下なら大幅ペナルティ

    results.append({
      "rt": rt, "st": st, "rbr": rbr, "ubr": ubr, "dbr": dbr, "hys": hys,
      "wRet": wRet, "worst": worst, "score": score, "scenarios": scenarios,
    })

    if score > bestScore:
      bestScore = score
      bestParams = results[-1]

    count += 1
    if count % 500 == 0:
      print(f"  {count}/{total} ... best score={bestScore:.1f} (wRet={bestParams['wRet']:.1f}%, worst={bestParams['worst']:.1f}%)")

  # 上位10件
  results.sort(key=lambda x: x["score"], reverse=True)
  print(f"\n{'=' * 90}")
  print(f"  上位10パラメータ")
  print(f"{'=' * 90}")
  print(f"  {'rank':>4s}  {'rt':>4s}  {'st':>4s}  {'rbr':>4s}  {'ubr':>4s}  {'dbr':>4s}  {'hys':>3s}  {'加重ret':>8s}  {'worst':>8s}  {'score':>7s}  bear    range   crash   bleed   burst   brkout")
  print(f"  {'-' * 130}")
  for i, r in enumerate(results[:10]):
    s = r["scenarios"]
    print(f"  {i+1:>4d}  {r['rt']:>4.0f}  {r['st']:>4.0f}  {r['rbr']:>4.1f}  {r['ubr']:>4.1f}  {r['dbr']:>4.1f}  {r['hys']:>3d}  {r['wRet']:>+7.1f}%  {r['worst']:>+7.1f}%  {r['score']:>7.1f}  {s['bear']:>+6.1f}  {s['range']:>+6.1f}  {s['crash_recovery']:>+6.1f}  {s['slow_bleed']:>+6.1f}  {s['bubble_burst']:>+6.1f}  {s['range_breakout']:>+6.1f}")

  print(f"\n  現行(v2.1): rt=4, st=8, rbr=0.5, ubr=0.2, dbr=0.3, hys=3")


if __name__ == "__main__":
  main()
