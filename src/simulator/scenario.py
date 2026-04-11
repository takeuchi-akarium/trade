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
  # (bb_weight, bb_ls_weight)
  "uptrend":   (1.00, 0.00),  # bb全力
  "range":     (0.70, 0.30),  # bb主体、bb_lsは補助
  "downtrend": (0.00, 0.00),  # 全退避
}


def detectRegime(close: float, trendMa: float) -> str:
  """現在の相場レジームを判定"""
  if np.isnan(trendMa):
    return "range"
  if close > trendMa * 1.02:
    return "uptrend"
  elif close < trendMa * 0.98:
    return "downtrend"
  else:
    return "range"


def runDynamicWeight(scenarioKey: str, initialCapital: float = 100_000,
                     feePct: float = 0.1, trendMaPeriod: int = 50) -> dict:
  """
  比率変動制: トレンドに応じてbb/bb_lsのweight配分を動的に変更。

  各足でレジーム判定 → 配分変更 → 各戦略のリターンをweight比率で合算。
  """
  import strategies
  from strategies.registry import getStrategy

  scenario = SCENARIOS[scenarioKey]
  data = scenario["fn"]()

  # 両戦略のシグナルを生成
  bbStrategy = getStrategy("bb")
  bbLsStrategy = getStrategy("bb_ls")

  dfBb = bbStrategy.generateSignals(data.copy())
  dfBbLs = bbLsStrategy.generateSignals(data.copy())

  # トレンド判定用
  trendMa = data["close"].rolling(trendMaPeriod).mean()

  # 各戦略を独立にバックテストし、日次リターンを計算
  from strategies.scalping.backtest import runBacktest, runBacktestLongShort

  _, eqBb = runBacktest(dfBb, initialCapital, feePct / 100)
  _, eqBbLs = runBacktestLongShort(dfBbLs, initialCapital, feePct / 100, stopLossPct=5.0)

  retBb = eqBb.pct_change().fillna(0)
  retBbLs = eqBbLs.pct_change().fillna(0)

  # 比率変動制でequityを構築
  equity = initialCapital
  equityList = []
  regimeHistory = []
  prevRegime = None

  for i in range(len(data)):
    close = data["close"].iloc[i]
    ma = trendMa.iloc[i]

    regime = detectRegime(close, ma)
    wBb, wBbLs = REGIME_WEIGHTS[regime]

    # レジーム切替時のリバランスコスト（片道手数料 x 2戦略分）
    if prevRegime is not None and regime != prevRegime:
      rebalanceCost = equity * feePct / 100 * 2
      equity -= rebalanceCost

    rBb = retBb.iloc[i] if i < len(retBb) else 0
    rBbLs = retBbLs.iloc[i] if i < len(retBbLs) else 0
    portfolioReturn = wBb * rBb + wBbLs * rBbLs

    equity *= (1 + portfolioReturn)
    equityList.append(equity)
    regimeHistory.append(regime)
    prevRegime = regime

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

  return {
    "scenario": scenario["name"],
    "scenarioKey": scenarioKey,
    "totalReturn": totalReturn,
    "finalValue": finalValue,
    "mdd": mdd,
    "regimeCounts": regimeCounts,
  }


def runDynamicComparison():
  """比率変動制 vs 固定配分の比較"""
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
    rBbLs = runScenario("bb_ls", sKey)

    regimeStr = " / ".join(f"{k}:{v}" for k, v in dynResult["regimeCounts"].items())

    print(f"  レジーム推移: {regimeStr}")
    print(f"  {'配分方式':<20s} {'リターン':>10s} {'最終資産':>10s} {'MDD':>10s}")
    print(f"  {'-' * 50}")
    print(f"  {'比率変動制':<20s} {dynResult['totalReturn']:>+9.2f}% {dynResult['finalValue']:>10,.0f} {dynResult['mdd']:>+9.2f}%")
    print(f"  {'bb単体':<20s} {rBb['metrics']['totalReturn']:>+9.2f}% {rBb['metrics']['finalValue']:>10,.0f} {rBb['metrics']['mdd']:>+9.2f}%")
    print(f"  {'bb_ls単体':<20s} {rBbLs['metrics']['totalReturn']:>+9.2f}% {rBbLs['metrics']['finalValue']:>10,.0f} {rBbLs['metrics']['mdd']:>+9.2f}%")

    allResults.append({
      "scenarioKey": sKey,
      "scenario": sInfo["name"],
      "probability": prob,
      "dynamic": dynResult,
      "bb": rBb["metrics"]["totalReturn"],
      "bbLs": rBbLs["metrics"]["totalReturn"],
    })

  # 確率加重サマリー
  print(f"\n{'=' * 70}")
  print(f"  確率加重 期待リターン")
  print(f"{'=' * 70}")

  dynExpected = sum(r["dynamic"]["totalReturn"] * r["probability"] for r in allResults)
  bbExpected = sum(r["bb"] * r["probability"] for r in allResults)
  bbLsExpected = sum(r["bbLs"] * r["probability"] for r in allResults)

  dynWorst = min(r["dynamic"]["totalReturn"] for r in allResults)
  bbWorst = min(r["bb"] for r in allResults)
  bbLsWorst = min(r["bbLs"] for r in allResults)

  print(f"  {'配分方式':<20s} {'期待リターン':>12s} {'最悪ケース':>12s}")
  print(f"  {'-' * 44}")
  print(f"  {'比率変動制':<20s} {dynExpected:>+11.2f}% {dynWorst:>+11.2f}%")
  print(f"  {'bb単体':<20s} {bbExpected:>+11.2f}% {bbWorst:>+11.2f}%")
  print(f"  {'bb_ls単体':<20s} {bbLsExpected:>+11.2f}% {bbLsWorst:>+11.2f}%")


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
  args = parser.parse_args()

  if args.dynamic:
    runDynamicComparison()
  else:
    names = [s.strip() for s in args.strategies.split(",")]
    runAllScenarios(names, sl=args.sl)
