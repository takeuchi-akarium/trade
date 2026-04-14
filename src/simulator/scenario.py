"""
シナリオシミュレーター

合成データで異なる相場環境を生成し、戦略を検証する。
バックテスト(過去データ)では見えないリスクを炙り出す。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# シナリオ別の合成データ生成
# ---------------------------------------------------------------------------

def _generateOhlcv(closes: np.ndarray, startDate: str = "2024-01-01") -> pd.DataFrame:
  """close配列からOHLCVデータフレームを生成"""
  n = len(closes)
  dates = pd.date_range(startDate, periods=n, freq="D")
  noise = np.random.RandomState(42)

  highs = closes * (1 + noise.uniform(0.005, 0.03, n))
  lows = closes * (1 - noise.uniform(0.005, 0.03, n))
  opens = closes * (1 + noise.normal(0, 0.01, n))
  volumes = noise.uniform(1000, 5000, n)

  return pd.DataFrame({
    "open": opens, "high": highs, "low": lows,
    "close": closes, "volume": volumes,
  }, index=dates)


def scenarioBear(days: int = 500, startPrice: float = 70000) -> pd.DataFrame:
  """
  シナリオ1: 下落相場
  高値から-60%まで下落し、底でもみ合い。2022年のBTC暴落を想定。
  """
  rng = np.random.RandomState(1)
  prices = [startPrice]
  for i in range(1, days):
    progress = i / days
    if progress < 0.4:
      # 前半: 急落 (-60%)
      drift = -0.003
      vol = 0.04
    elif progress < 0.7:
      # 中盤: 底でもみ合い
      drift = 0.0
      vol = 0.03
    else:
      # 後半: じわじわ回復
      drift = 0.001
      vol = 0.025
    ret = drift + vol * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


def scenarioRange(days: int = 500, startPrice: float = 50000) -> pd.DataFrame:
  """
  シナリオ2: レンジ相場
  ±20%の範囲でレンジを繰り返す。明確なトレンドなし。
  """
  rng = np.random.RandomState(2)
  prices = [startPrice]
  for i in range(1, days):
    # 平均回帰力: 中心価格から離れるほど戻る力が強い
    deviation = (prices[-1] - startPrice) / startPrice
    meanRevert = -deviation * 0.05
    ret = meanRevert + 0.03 * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


def scenarioCrashRecovery(days: int = 500, startPrice: float = 60000) -> pd.DataFrame:
  """
  シナリオ3: 急落→急回復(V字)
  FTXショックやコロナショックのような急落後、急速にリカバリー。
  """
  rng = np.random.RandomState(3)
  prices = [startPrice]
  for i in range(1, days):
    progress = i / days
    if progress < 0.3:
      # 前半: 緩やかな上昇
      drift = 0.001
      vol = 0.02
    elif progress < 0.4:
      # 急落フェーズ (-50%)
      drift = -0.012
      vol = 0.06
    elif progress < 0.55:
      # 底打ち→急回復
      drift = 0.008
      vol = 0.05
    else:
      # 回復→新高値
      drift = 0.002
      vol = 0.025
    ret = drift + vol * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


def scenarioSlowBleed(days: int = 500, startPrice: float = 55000) -> pd.DataFrame:
  """
  シナリオ4: ダラダラ下落
  明確な暴落なし。じわじわ-40%。トレンド判定が「レンジ」と「下落」を行き来する。
  """
  rng = np.random.RandomState(4)
  prices = [startPrice]
  for i in range(1, days):
    # 小さなマイナスドリフト + ときどき反発
    drift = -0.001
    vol = 0.025
    if i % 60 < 15:  # 60日サイクルで15日間の反発
      drift = 0.002
    ret = drift + vol * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


def scenarioBubbleBurst(days: int = 500, startPrice: float = 40000) -> pd.DataFrame:
  """
  シナリオ5: バブル崩壊
  急騰(3倍)→ピーク→急落(-70%)。上昇レジームから下落への切替速度がカギ。
  """
  rng = np.random.RandomState(5)
  prices = [startPrice]
  for i in range(1, days):
    progress = i / days
    if progress < 0.4:
      # バブル膨張: 急騰
      drift = 0.005
      vol = 0.035
    elif progress < 0.45:
      # ピーク: 乱高下
      drift = 0.0
      vol = 0.06
    elif progress < 0.65:
      # 崩壊: 急落
      drift = -0.008
      vol = 0.05
    else:
      # 底這い
      drift = 0.0005
      vol = 0.02
    ret = drift + vol * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


def scenarioRangeBreakout(days: int = 500, startPrice: float = 45000) -> pd.DataFrame:
  """
  シナリオ6: ヨコヨコ→急騰
  長期レンジ(70%)の後、突然ブレイクアウトして急騰。乗り遅れリスクの検証。
  """
  rng = np.random.RandomState(6)
  prices = [startPrice]
  for i in range(1, days):
    progress = i / days
    if progress < 0.7:
      # 長期レンジ
      deviation = (prices[-1] - startPrice) / startPrice
      meanRevert = -deviation * 0.05
      ret = meanRevert + 0.025 * rng.randn()
    else:
      # ブレイクアウト→急騰
      drift = 0.006
      vol = 0.04
      ret = drift + vol * rng.randn()
    prices.append(prices[-1] * (1 + ret))

  return _generateOhlcv(np.array(prices))


SCENARIOS = {
  "bear": {
    "fn": scenarioBear,
    "name": "下落→回復",
    "probability": 0.15,
    "rationale": "FRB利下げ停滞、規制強化→底打ち後に緩やかな回復",
  },
  "range": {
    "fn": scenarioRange,
    "name": "レンジ (±20%)",
    "probability": 0.25,
    "rationale": "ETF材料出尽くし、半減期織り込み済み",
  },
  "crash_recovery": {
    "fn": scenarioCrashRecovery,
    "name": "急落→V字回復",
    "probability": 0.10,
    "rationale": "取引所破綻・地政学リスク→緩和マネーで急回復",
  },
  "slow_bleed": {
    "fn": scenarioSlowBleed,
    "name": "ダラダラ下落 (-40%)",
    "probability": 0.20,
    "rationale": "明確な暴落なくじわじわ下落。レジーム判定が揺れる",
  },
  "bubble_burst": {
    "fn": scenarioBubbleBurst,
    "name": "バブル崩壊 (3倍→-70%)",
    "probability": 0.15,
    "rationale": "急騰後の急落。切替速度が間に合うか",
  },
  "range_breakout": {
    "fn": scenarioRangeBreakout,
    "name": "ヨコヨコ→急騰",
    "probability": 0.15,
    "rationale": "長期レンジ後にブレイクアウト。乗り遅れリスク",
  },
}


# ---------------------------------------------------------------------------
# シミュレーション実行
# ---------------------------------------------------------------------------

def runScenario(strategyName: str, scenarioKey: str, sl: float = None) -> dict:
  """1つの戦略 x 1つのシナリオを実行"""
  import strategies
  from strategies.registry import getStrategy
  from simulator.metrics import ensureMetrics

  strategy = getStrategy(strategyName)
  scenario = SCENARIOS[scenarioKey]
  data = scenario["fn"]()

  params = {"symbol": "SCENARIO", "interval": "1d"}
  if sl is not None:
    params["sl"] = sl

  result = strategy.backtest(data, **params)
  initialCapital = result.equity.iloc[0] if len(result.equity) > 0 else 100_000
  result.metrics = ensureMetrics(result.metrics, result.trades, result.equity, initialCapital)

  return {
    "strategy": strategyName,
    "scenario": scenario["name"],
    "scenarioKey": scenarioKey,
    "metrics": result.metrics,
    "trades": len([t for t in result.trades if t.get("type") in ("sell", "close")]),
    "startPrice": data["close"].iloc[0],
    "endPrice": data["close"].iloc[-1],
  }


def runAllScenarios(strategyNames: list[str], sl: float = None):
  """複数戦略 x 全シナリオを実行して結果を表示"""
  print(f"\n{'=' * 70}")
  print(f"  シナリオシミュレーション")
  print(f"{'=' * 70}")

  results = []
  for sKey, sInfo in SCENARIOS.items():
    data = sInfo["fn"]()
    pStart = data["close"].iloc[0]
    pEnd = data["close"].iloc[-1]
    pChange = (pEnd - pStart) / pStart * 100
    prob = sInfo["probability"]
    print(f"\n  [{sInfo['name']}]  実現確率: {prob:.0%}")
    print(f"  根拠: {sInfo['rationale']}")
    print(f"  価格: {pStart:,.0f} → {pEnd:,.0f} ({pChange:+.1f}%)")
    print(f"  {'戦略':<18s} {'リターン':>10s} {'最終資産':>10s} {'MDD':>10s} {'勝率':>8s} {'取引数':>6s}")
    print(f"  {'-' * 62}")

    for name in strategyNames:
      r = runScenario(name, sKey, sl=sl)
      m = r["metrics"]
      print(f"  {name:<18s} {m['totalReturn']:>+9.2f}% {m['finalValue']:>10,.0f} {m['mdd']:>+9.2f}% {m['winRate']:>7.1f}% {r['trades']:>6d}")
      results.append(r)

  # 確率加重サマリー
  print(f"\n{'=' * 70}")
  print(f"  総合評価（確率加重）")
  print(f"{'=' * 70}")
  print(f"  {'戦略':<18s} {'期待リターン':>12s} {'最悪ケース':>12s} {'最悪シナリオ':<20s}")
  print(f"  {'-' * 62}")
  for name in strategyNames:
    stratResults = [r for r in results if r["strategy"] == name]
    # 確率加重リターン
    expectedReturn = sum(
      r["metrics"]["totalReturn"] * SCENARIOS[r["scenarioKey"]]["probability"]
      for r in stratResults
    )
    worstResult = min(stratResults, key=lambda r: r["metrics"]["totalReturn"])
    worstReturn = worstResult["metrics"]["totalReturn"]
    worstName = worstResult["scenario"]
    print(f"  {name:<18s} {expectedReturn:>+11.2f}% {worstReturn:>+11.2f}% {worstName}")

  print(f"\n  ※ 期待リターン = Σ(シナリオ確率 × リターン)")
  print(f"  ※ 実現確率は主観的な見通しに基づく推定値です")


# ---------------------------------------------------------------------------
# 比率変動制シミュレーション
# ---------------------------------------------------------------------------

REGIME_WEIGHTS = {
  # (bb_weight, ema_don_weight, bb_ls_weight)
  "uptrend":   (0.30, 0.70, 0.00),  # ema_don主役、bbは押し目
  "range":     (0.70, 0.10, 0.20),  # bb主体、ema_don少量
  "downtrend": (0.00, 0.00, 0.00),  # 全退避
}

# 配分パターン比較用（固定レジーム型）
ALLOCATION_PATTERNS = {
  "current": {
    "label": "現行ミックス",
    "type": "fixed",
    "weights": REGIME_WEIGHTS,
  },
  "regime_solo": {
    "label": "得意戦略のみ",
    "type": "fixed",
    "weights": {
      "uptrend":   (0.00, 1.00, 0.00),
      "range":     (1.00, 0.00, 0.00),
      "downtrend": (0.00, 0.00, 0.00),
    },
  },
  "gradient": {
    "label": "段階制",
    "type": "gradient",
    # 乖離率の閾値で参加戦略数を動的に変える
    # (bb, ema_don, bb_ls)
    # v2.2: シナリオ探索で最適化 (bb厚め+hys4日)
    "levels": {
      # SMA50乖離率 > +8%: 強uptrend → ema_don単独
      "strong_up":   {"threshold": 8.0,  "weights": (0.00, 1.00, 0.00)},
      # +3% ~ +8%: 通常uptrend → ema_don主力 + bb補助
      "uptrend":     {"threshold": 3.0,  "weights": (0.30, 0.70, 0.00)},
      # -3% ~ +3%: range → bb主力 + ema_don補助
      "range":       {"threshold": -3.0, "weights": (0.70, 0.30, 0.00)},
      # -8% ~ -3%: 通常downtrend → bb押し目のみ（縮小ポジション）
      "downtrend":   {"threshold": -8.0, "weights": (0.50, 0.00, 0.00)},
      # < -8%: 強downtrend → 全退避
      "strong_down": {"threshold": None, "weights": (0.00, 0.00, 0.00)},
    },
    # NaN/無効値時のデフォルトweight
    "nanDefault": (0.70, 0.30, 0.00),
    # レジーム遷移のヒステリシス（N日連続で閾値を超えたら遷移）
    "hysteresis": 4,
  },
}


def _sortLevels(levels: dict) -> list:
  """levelsをthreshold降順にソート。threshold=Noneは末尾"""
  return sorted(
    levels.items(),
    key=lambda x: x[1]["threshold"] if x[1]["threshold"] is not None else float("-inf"),
    reverse=True,
  )


# gradient用のソート済みレベルをモジュールレベルでキャッシュ
_GRADIENT_SORTED = _sortLevels(ALLOCATION_PATTERNS["gradient"]["levels"])
_GRADIENT_HYSTERESIS = ALLOCATION_PATTERNS["gradient"].get("hysteresis", 1)


def detectRegime(close: float, trendMa: float) -> str:
  """現在の相場レジームを判定（3段階）"""
  if np.isnan(trendMa):
    return "range"
  if close > trendMa * 1.02:
    return "uptrend"
  elif close < trendMa * 0.98:
    return "downtrend"
  else:
    return "range"


def _gradientWeights(close: float, trendMa: float, sortedLevels: list, nanDefault: tuple) -> tuple:
  """乖離率に応じて段階的にweightを返す。sortedLevelsはthreshold降順のリスト"""
  if np.isnan(trendMa) or trendMa == 0:
    return nanDefault
  dev = (close - trendMa) / trendMa * 100
  for _, info in sortedLevels:
    if info["threshold"] is not None and dev > info["threshold"]:
      return info["weights"]
  return sortedLevels[-1][1]["weights"]


def _prepareBacktestData(scenarioKey: str, initialCapital: float, feePct: float, trendMaPeriod: int):
  """シナリオのデータとバックテスト結果を準備（共通化）"""
  scenario = SCENARIOS[scenarioKey]
  data = scenario["fn"]()
  return _runBacktestOnData(data, initialCapital, feePct, trendMaPeriod)


def _runBacktestOnData(data, initialCapital: float, feePct: float, trendMaPeriod: int):
  """任意のOHLCVデータで3戦略のバックテストを実行"""
  import strategies
  from strategies.registry import getStrategy
  from strategies.scalping.backtest import runBacktest, runBacktestLongShort

  bbStrategy = getStrategy("bb")
  emaStrategy = getStrategy("ema_don")
  bbLsStrategy = getStrategy("bb_ls")

  dfBb = bbStrategy.generateSignals(data.copy())
  dfEma = emaStrategy.generateSignals(data.copy(), short=10, long=50)
  dfBbLs = bbLsStrategy.generateSignals(data.copy())

  # shift(1): 前日までのデータでレジーム判定（look-ahead bias防止）
  trendMa = data["close"].rolling(trendMaPeriod).mean().shift(1)

  _, eqBb = runBacktest(dfBb, initialCapital, feePct)
  _, eqEma = runBacktest(dfEma, initialCapital, feePct)
  _, eqBbLs = runBacktestLongShort(dfBbLs, initialCapital, feePct, stopLossPct=5.0)

  retBb = eqBb.pct_change().fillna(0)
  retEma = eqEma.pct_change().fillna(0)
  retBbLs = eqBbLs.pct_change().fillna(0)

  return data, trendMa, retBb, retEma, retBbLs


def runDynamicWeight(scenarioKey: str = None, initialCapital: float = 100_000,
                     feePct: float = 0.1, trendMaPeriod: int = 50,
                     weights: dict = None, gradientLevels: dict = None,
                     nanDefault: tuple = None,
                     precomputed: tuple = None) -> dict:
  """
  比率変動制: トレンドに応じてbb/bb_lsのweight配分を動的に変更。

  weights: 固定レジーム型の配分dict
  gradientLevels: 段階制のlevels dict（乖離率ベース）
  nanDefault: gradient時のNaN/無効値フォールバックweight
  precomputed: _prepareBacktestDataの戻り値（再利用で高速化）
  """
  if precomputed:
    data, trendMa, retBb, retEma, retBbLs = precomputed
  elif scenarioKey:
    data, trendMa, retBb, retEma, retBbLs = _prepareBacktestData(
      scenarioKey, initialCapital, feePct, trendMaPeriod)
  else:
    raise ValueError("scenarioKey or precomputed is required")

  # gradient用のソート済みレベル（キャッシュがあれば使用）
  if gradientLevels:
    if gradientLevels is ALLOCATION_PATTERNS["gradient"]["levels"]:
      sortedLevels = _GRADIENT_SORTED
    else:
      sortedLevels = _sortLevels(gradientLevels)
    if nanDefault is None:
      nanDefault = (0.60, 0.10, 0.30)
  else:
    sortedLevels = None

  # ヒステリシス: N日連続で同じweightが示されたら遷移
  hysteresis = ALLOCATION_PATTERNS["gradient"].get("hysteresis", 1) if gradientLevels is None or gradientLevels is ALLOCATION_PATTERNS["gradient"]["levels"] else 1

  # 比率変動制でequityを構築
  equity = initialCapital
  equityList = []
  regimeHistory = []
  prevWeights = None
  candidateWeights = None
  candidateCount = 0

  # 前日の終値でレジーム判定（当日のリターンに適用）
  prevClose = data["close"].shift(1)
  for i in range(len(data)):
    close = prevClose.iloc[i] if i > 0 and not np.isnan(prevClose.iloc[i]) else data["close"].iloc[i]
    ma = trendMa.iloc[i]

    if sortedLevels:
      rawWeights = _gradientWeights(close, ma, sortedLevels, nanDefault)
      regime = detectRegime(close, ma)
    else:
      regime = detectRegime(close, ma)
      rawWeights = (weights or REGIME_WEIGHTS)[regime]

    # ヒステリシス適用
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

    # weight変化量に比例したリバランスコスト
    if prevWeights is not None and curWeights != prevWeights:
      weightDelta = sum(abs(a - b) for a, b in zip(curWeights, prevWeights))
      rebalanceCost = equity * feePct / 100 * weightDelta
      equity -= rebalanceCost
    prevWeights = curWeights

    rBb = retBb.iloc[i] if i < len(retBb) else 0
    rEma = retEma.iloc[i] if i < len(retEma) else 0
    rBbLs = retBbLs.iloc[i] if i < len(retBbLs) else 0
    portfolioReturn = wBb * rBb + wEma * rEma + wBbLs * rBbLs

    equity *= (1 + portfolioReturn)
    equityList.append(equity)
    regimeHistory.append(regime)

  eqSeries = pd.Series(equityList, index=data.index)
  finalValue = equityList[-1]
  totalReturn = (finalValue - initialCapital) / initialCapital * 100

  # MDD
  peak = eqSeries.expanding().max()
  dd = (eqSeries - peak) / peak * 100
  mdd = dd.min()

  # レジーム分布
  regimeCounts = {}
  for r in regimeHistory:
    regimeCounts[r] = regimeCounts.get(r, 0) + 1

  scenarioName = SCENARIOS[scenarioKey]["name"] if scenarioKey else "real_data"
  return {
    "scenario": scenarioName,
    "scenarioKey": scenarioKey or "real_data",
    "totalReturn": totalReturn,
    "finalValue": finalValue,
    "mdd": mdd,
    "regimeCounts": regimeCounts,
  }


def runDynamicComparison():
  """比率変動制 vs 固定配分の比較（レガシー。新規はrunAllocationComparisonを使用）"""
  print(f"\n{'=' * 70}")
  print(f"  比率変動制 vs 固定配分 比較")
  print(f"{'=' * 70}")

  allResults = []

  for sKey, sInfo in SCENARIOS.items():
    prob = sInfo["probability"]
    print(f"\n  [{sInfo['name']}]  実現確率: {prob:.0%}")

    # 比率変動制
    dynResult = runDynamicWeight(sKey)

    # 個別戦略
    rBb = runScenario("bb", sKey)
    rEma = runScenario("ema_don", sKey)
    rBbLs = runScenario("bb_ls", sKey)

    regimeStr = " / ".join(f"{k}:{v}" for k, v in dynResult["regimeCounts"].items())

    print(f"  レジーム推移: {regimeStr}")
    print(f"  {'配分方式':<20s} {'リターン':>10s} {'最終資産':>10s} {'MDD':>10s}")
    print(f"  {'-' * 50}")
    print(f"  {'比率変動制':<20s} {dynResult['totalReturn']:>+9.2f}% {dynResult['finalValue']:>10,.0f} {dynResult['mdd']:>+9.2f}%")
    print(f"  {'bb単体':<20s} {rBb['metrics']['totalReturn']:>+9.2f}% {rBb['metrics']['finalValue']:>10,.0f} {rBb['metrics']['mdd']:>+9.2f}%")
    print(f"  {'ema単体':<20s} {rEma['metrics']['totalReturn']:>+9.2f}% {rEma['metrics']['finalValue']:>10,.0f} {rEma['metrics']['mdd']:>+9.2f}%")
    print(f"  {'bb_ls単体':<20s} {rBbLs['metrics']['totalReturn']:>+9.2f}% {rBbLs['metrics']['finalValue']:>10,.0f} {rBbLs['metrics']['mdd']:>+9.2f}%")

    allResults.append({
      "scenarioKey": sKey,
      "scenario": sInfo["name"],
      "probability": prob,
      "dynamic": dynResult,
      "bb": rBb["metrics"]["totalReturn"],
      "ema": rEma["metrics"]["totalReturn"],
      "bbLs": rBbLs["metrics"]["totalReturn"],
    })

  # 確率加重サマリー
  print(f"\n{'=' * 70}")
  print(f"  確率加重 期待リターン")
  print(f"{'=' * 70}")

  dynExpected = sum(r["dynamic"]["totalReturn"] * r["probability"] for r in allResults)
  bbExpected = sum(r["bb"] * r["probability"] for r in allResults)
  emaExpected = sum(r["ema"] * r["probability"] for r in allResults)
  bbLsExpected = sum(r["bbLs"] * r["probability"] for r in allResults)

  dynWorst = min(r["dynamic"]["totalReturn"] for r in allResults)
  bbWorst = min(r["bb"] for r in allResults)
  emaWorst = min(r["ema"] for r in allResults)
  bbLsWorst = min(r["bbLs"] for r in allResults)

  print(f"  {'配分方式':<20s} {'期待リターン':>12s} {'最悪ケース':>12s}")
  print(f"  {'-' * 44}")
  print(f"  {'比率変動制':<20s} {dynExpected:>+11.2f}% {dynWorst:>+11.2f}%")
  print(f"  {'bb単体':<20s} {bbExpected:>+11.2f}% {bbWorst:>+11.2f}%")
  print(f"  {'ema単体':<20s} {emaExpected:>+11.2f}% {emaWorst:>+11.2f}%")
  print(f"  {'bb_ls単体':<20s} {bbLsExpected:>+11.2f}% {bbLsWorst:>+11.2f}%")


def _printPatternSummary(verbose: bool = True):
  """配分パターンの説明を表示"""
  print(f"\n  テスト対象:")
  for pKey, pInfo in ALLOCATION_PATTERNS.items():
    if pInfo["type"] == "fixed":
      w = pInfo["weights"]
      parts = []
      for regime in ["uptrend", "range", "downtrend"]:
        bb, ema, ls = w[regime]
        if bb + ema + ls == 0:
          parts.append(f"{regime}:退避")
        else:
          active = []
          if bb > 0: active.append(f"bb{bb:.0%}")
          if ema > 0: active.append(f"ema{ema:.0%}")
          if ls > 0: active.append(f"ls{ls:.0%}")
          parts.append(f"{regime}:{'+'.join(active)}")
      print(f"    {pInfo['label']:<16s} {' / '.join(parts)}")
    elif pInfo["type"] == "gradient":
      if verbose:
        print(f"    {pInfo['label']:<16s} 乖離率で参加戦略数が変化:")
        for lKey, lInfo in pInfo["levels"].items():
          bb, ema, ls = lInfo["weights"]
          thr = lInfo["threshold"]
          active = []
          if bb > 0: active.append(f"bb{bb:.0%}")
          if ema > 0: active.append(f"ema{ema:.0%}")
          if ls > 0: active.append(f"ls{ls:.0%}")
          wStr = "+".join(active) if active else "退避"
          thrStr = f">{thr:+.0f}%" if thr is not None else "それ以下"
          print(f"      {lKey:<14s} ({thrStr:<8s}) → {wStr}  [{len(active)}戦略]")
      else:
        print(f"    {pInfo['label']:<16s} 乖離率で参加戦略数が変化 (5段階)")


def runAllocationComparison():
  """配分パターン比較: 現行 vs 得意戦略のみ vs 段階制"""
  print(f"\n{'=' * 70}")
  print(f"  DART配分パターン比較")
  print(f"{'=' * 70}")

  _printPatternSummary(verbose=True)

  allResults = {pKey: [] for pKey in ALLOCATION_PATTERNS}

  for sKey, sInfo in SCENARIOS.items():
    prob = sInfo["probability"]
    data = sInfo["fn"]()
    pStart = data["close"].iloc[0]
    pEnd = data["close"].iloc[-1]
    pChange = (pEnd - pStart) / pStart * 100

    # バックテスト結果を共有して高速化
    precomputed = _prepareBacktestData(sKey, 100_000, 0.1, 50)

    print(f"\n  [{sInfo['name']}]  確率: {prob:.0%}  価格: {pStart:,.0f} → {pEnd:,.0f} ({pChange:+.1f}%)")
    print(f"  {'パターン':<16s} {'リターン':>10s} {'MDD':>10s} {'レジーム分布'}")
    print(f"  {'-' * 65}")

    for pKey, pInfo in ALLOCATION_PATTERNS.items():
      if pInfo["type"] == "gradient":
        result = runDynamicWeight(sKey, gradientLevels=pInfo["levels"], nanDefault=pInfo.get("nanDefault"), precomputed=precomputed)
      else:
        result = runDynamicWeight(sKey, weights=pInfo["weights"], precomputed=precomputed)
      regimeStr = " ".join(f"{k[0].upper()}:{v}" for k, v in result["regimeCounts"].items())
      print(f"  {pInfo['label']:<16s} {result['totalReturn']:>+9.2f}% {result['mdd']:>+9.2f}% {regimeStr}")
      allResults[pKey].append({
        "scenarioKey": sKey,
        "probability": prob,
        **result,
      })

  # 確率加重サマリー
  print(f"\n{'=' * 70}")
  print(f"  確率加重 総合評価")
  print(f"{'=' * 70}")
  print(f"  {'パターン':<16s} {'期待リターン':>12s} {'最悪ケース':>12s} {'期待MDD':>10s} {'リターン/MDD':>12s}")
  print(f"  {'-' * 64}")

  for pKey, pInfo in ALLOCATION_PATTERNS.items():
    results = allResults[pKey]
    expectedReturn = sum(r["totalReturn"] * r["probability"] for r in results)
    worstReturn = min(r["totalReturn"] for r in results)
    expectedMdd = sum(r["mdd"] * r["probability"] for r in results)
    ratio = expectedReturn / abs(expectedMdd) if expectedMdd != 0 else 0
    print(f"  {pInfo['label']:<16s} {expectedReturn:>+11.2f}% {worstReturn:>+11.2f}% {expectedMdd:>+9.2f}% {ratio:>11.2f}")


def runAllocationBacktest(years: int = 3):
  """実データ(Binance BTCUSDT)で配分パターンを比較バックテスト"""
  import strategies
  from strategies.registry import getStrategy

  print(f"\n{'=' * 70}")
  print(f"  DART配分パターン バックテスト (BTCUSDT {years}Y)")
  print(f"{'=' * 70}")

  # 実データ取得
  strategy = getStrategy("bb")
  data = strategy.fetchData(symbol="BTCUSDT", interval="1d", years=years)
  pStart = data["close"].iloc[0]
  pEnd = data["close"].iloc[-1]
  pChange = (pEnd - pStart) / pStart * 100
  print(f"  期間: {data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')} ({len(data)}日)")
  print(f"  BTC: {pStart:,.0f} -> {pEnd:,.0f} ({pChange:+.1f}%)")

  # バックテスト結果を共有
  precomputed = _runBacktestOnData(data, 100_000, 0.1, 50)

  _printPatternSummary(verbose=False)

  # 各パターンでバックテスト
  print(f"\n  {'パターン':<16s} {'リターン':>10s} {'MDD':>10s} {'最終資産':>12s} {'リターン/MDD':>12s} {'レジーム分布'}")
  print(f"  {'-' * 75}")

  for pKey, pInfo in ALLOCATION_PATTERNS.items():
    if pInfo["type"] == "gradient":
      result = runDynamicWeight(precomputed=precomputed, gradientLevels=pInfo["levels"])
    else:
      result = runDynamicWeight(precomputed=precomputed, weights=pInfo["weights"])
    regimeStr = " ".join(f"{k[0].upper()}:{v}" for k, v in result["regimeCounts"].items())
    ratio = result["totalReturn"] / abs(result["mdd"]) if result["mdd"] != 0 else 0
    print(f"  {pInfo['label']:<16s} {result['totalReturn']:>+9.2f}% {result['mdd']:>+9.2f}% {result['finalValue']:>12,.0f} {ratio:>11.2f} {regimeStr}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser(description="シナリオシミュレーション")
  parser.add_argument("--strategies", default="bb,bb_ls,bb_trend,bb_trend_ls",
                      help="comma-separated strategy names")
  parser.add_argument("--sl", type=float, default=None, help="stop loss pct")
  parser.add_argument("--dynamic", action="store_true", help="run dynamic weight comparison")
  parser.add_argument("--allocation", action="store_true", help="run allocation pattern comparison (synthetic)")
  parser.add_argument("--backtest", action="store_true", help="run allocation backtest (real data)")
  parser.add_argument("--years", type=int, default=3, help="years of data for backtest")
  args = parser.parse_args()

  if args.backtest:
    runAllocationBacktest(years=args.years)
  elif args.allocation:
    runAllocationComparison()
  elif args.dynamic:
    runDynamicComparison()
  else:
    names = [s.strip() for s in args.strategies.split(",")]
    runAllScenarios(names, sl=args.sl)
