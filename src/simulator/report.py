"""
共通レポート出力

バックテスト結果をJSONで data/simulations/ に保存する。
ブラウザでの表示は web/app.py の /simulations ページが担当。
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from strategies.base import BacktestResult

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "simulations"
BENCH_DIR = OUTPUT_DIR / "bench"
LIVE_DIR = OUTPUT_DIR / "live"


def printResult(result: BacktestResult) -> None:
  """ターミナルにメトリクスサマリーを表示"""
  m = result.metrics
  print(f"\n{'=' * 60}")
  print(f"  {result.strategyName}  |  {result.symbol}  {result.interval}")
  print(f"{'=' * 60}")

  rows = [
    ("総リターン", f"{m.get('totalReturn', 0):+.2f}%"),
    ("最終資産", f"{m.get('finalValue', 0):,.0f}"),
    ("トレード回数", f"{m.get('totalTrades', 0)}"),
    ("勝率", f"{m.get('winRate', 0):.1f}%"),
    ("PF", f"{m.get('profitFactor', 0):.2f}") if "profitFactor" in m else None,
    ("MDD", f"{m.get('mdd', 0):.2f}%"),
    ("年率リターン", f"{m.get('annualReturn', 0):.2f}%") if "annualReturn" in m else None,
    ("シャープレシオ", f"{m.get('sharpe', 0):.2f}") if "sharpe" in m else None,
  ]
  for row in rows:
    if row:
      print(f"  {row[0]:<16s} : {row[1]:>14s}")


def _serializeResult(result: BacktestResult) -> dict:
  """BacktestResult をJSON-serializable な dict に変換"""
  equity = result.equity
  initialCapital = equity.iloc[0] if len(equity) > 0 else 100_000

  # エクイティを間引き（最大500点）
  if len(equity) > 500:
    step = len(equity) // 500
    equitySampled = equity.iloc[::step]
  else:
    equitySampled = equity

  equityData = []
  for dt, val in equitySampled.items():
    equityData.append({
      "date": dt.isoformat() if hasattr(dt, "isoformat") else str(dt),
      "value": round(float(val), 2),
      "pct": round((float(val) / initialCapital - 1) * 100, 2),
    })

  return {
    "strategyName": result.strategyName,
    "symbol": result.symbol,
    "interval": result.interval,
    "metrics": result.metrics,
    "params": result.params,
    "equity": equityData,
    "tradeCount": len(result.trades),
    "savedAt": datetime.now().isoformat(),
  }


def saveResult(result: BacktestResult) -> Path:
  """バックテスト結果をJSONファイルに保存"""
  OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
  ts = datetime.now().strftime("%Y%m%d_%H%M%S")
  name = result.strategyName.replace(" ", "_").replace("/", "-")
  symbol = result.symbol.replace(" ", "_").replace("/", "-")
  filename = f"{name}_{symbol}_{ts}.json"
  outPath = OUTPUT_DIR / filename

  data = _serializeResult(result)
  outPath.write_text(
    json.dumps(data, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )
  print(f"  結果保存: {outPath}")
  return outPath


def saveCompare(results: list[BacktestResult]) -> Path:
  """複数戦略の比較結果をJSONファイルに保存"""
  OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
  ts = datetime.now().strftime("%Y%m%d_%H%M%S")
  symbol = results[0].symbol.replace(" ", "_").replace("/", "-") if results else "unknown"
  filename = f"compare_{symbol}_{ts}.json"
  outPath = OUTPUT_DIR / filename

  # リターン降順ソート
  sorted_results = sorted(results, key=lambda r: r.metrics.get("totalReturn", 0), reverse=True)
  data = {
    "type": "compare",
    "symbol": results[0].symbol if results else "",
    "results": [_serializeResult(r) for r in sorted_results],
    "savedAt": datetime.now().isoformat(),
  }

  outPath.write_text(
    json.dumps(data, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )
  print(f"  比較結果保存: {outPath}")
  return outPath


# ---------------------------------------------------------------------------
# bench -統一ベンチマーク出力
# ---------------------------------------------------------------------------

def printBenchBacktest(results: list[BacktestResult], symbol: str, interval: str,
                       years: int, sl: float = None, tp: float = None) -> None:
  """バックテスト結果をテーブル+示唆で表示"""
  if not results:
    print("  結果がありません")
    return

  sorted_r = sorted(results, key=lambda r: r.metrics.get("totalReturn", 0), reverse=True)

  # ヘッダー
  opts = f"{symbol} {interval}  |  {years}年"
  if sl is not None:
    opts += f"  |  SL: {sl}%"
  if tp is not None:
    opts += f"  |  TP: {tp}%"
  print(f"\n{'=' * 72}")
  print(f"  BACKTEST  |  {opts}")
  print(f"{'=' * 72}")
  print()
  print(f"  {'戦略':<16s} {'リターン':>8s} {'MDD':>8s} {'シャープ':>8s} {'勝率':>8s} {'PF':>8s} {'取引数':>6s}")
  print(f"  {'─' * 66}")

  for r in sorted_r:
    m = r.metrics
    pf = m.get("profitFactor", 0)
    pfStr = f"{pf:.2f}" if pf < 1000 else f"{pf:.0f}"
    print(f"  {r.strategyName:<16s} {m.get('totalReturn', 0):>+7.1f}% {m.get('mdd', 0):>+7.1f}% "
          f"{m.get('sharpe', 0):>8.2f} {m.get('winRate', 0):>7.1f}% {pfStr:>8s} {m.get('totalTrades', 0):>6d}")

  # 示唆
  insights = _generateBacktestInsights(sorted_r)
  if insights:
    print(f"\n  ── 示唆 ──")
    for line in insights:
      print(f"  - {line}")
  print()


def printBenchScenario(scenarioResults: list[dict], strategyNames: list[str],
                       scenarios: dict, sl: float = None) -> None:
  """シナリオテスト結果をテーブル+示唆で表示"""
  opts = "6シナリオ確率加重"
  if sl is not None:
    opts += f"  |  SL: {sl}%"
  print(f"\n{'=' * 80}")
  print(f"  SCENARIO  |  {opts}")
  print(f"{'=' * 80}")

  # 略称マッピング
  scenarioKeys = list(scenarios.keys())
  shortNames = {
    "bear": "bear", "range": "range", "crash_recovery": "crash",
    "slow_bleed": "bleed", "bubble_burst": "burst", "range_breakout": "brkout",
  }

  # ヘッダー
  header = f"  {'戦略':<14s} {'加重':>6s}"
  for sk in scenarioKeys:
    header += f" {shortNames.get(sk, sk[:6]):>7s}"
  print()
  print(header)
  print(f"  {'─' * (14 + 6 + len(scenarioKeys) * 8)}")

  # 戦略ごとの集計
  summaries = []
  for name in strategyNames:
    stratResults = [r for r in scenarioResults if r["strategy"] == name]
    if not stratResults:
      continue

    expectedReturn = sum(
      r["metrics"]["totalReturn"] * scenarios[r["scenarioKey"]]["probability"]
      for r in stratResults
    )

    row = f"  {name:<14s} {expectedReturn:>+5.1f}%"
    perScenario = {}
    for sk in scenarioKeys:
      sr = next((r for r in stratResults if r["scenarioKey"] == sk), None)
      ret = sr["metrics"]["totalReturn"] if sr else 0
      perScenario[sk] = ret
      row += f" {ret:>+6.1f}%"

    summaries.append({
      "name": name,
      "expected": expectedReturn,
      "perScenario": perScenario,
      "results": stratResults,
    })
    print(row)

  # 示唆
  insights = _generateScenarioInsights(summaries, scenarios)
  if insights:
    print(f"\n  ── 示唆 ──")
    for line in insights:
      print(f"  - {line}")
  print()


def _generateBacktestInsights(sortedResults: list[BacktestResult]) -> list[str]:
  """バックテスト結果から示唆を生成"""
  if not sortedResults:
    return []

  insights = []
  metrics = [(r.strategyName, r.metrics) for r in sortedResults]

  # 最高リターン + MDDリスク
  best = metrics[0]
  mdd = best[1].get("mdd", 0)
  insights.append(
    f"最高リターン: {best[0]} ({best[1].get('totalReturn', 0):+.1f}%)"
    + (f" ただしMDD {mdd:.1f}%で資金の{abs(mdd)/10:.0f}割を一時失う" if mdd < -20 else ""))

  # 最低リスク（MDD）
  lowestMdd = min(metrics, key=lambda x: abs(x[1].get("mdd", -100)))
  if lowestMdd[0] != best[0]:
    ret = lowestMdd[1].get("totalReturn", 0)
    insights.append(
      f"最低リスク: {lowestMdd[0]} (MDD {lowestMdd[1].get('mdd', 0):.1f}%)"
      + (f" だがリターン {ret:+.1f}%" if ret < best[1].get("totalReturn", 0) * 0.5 else ""))

  # シャープレシオ最高
  bestSharpe = max(metrics, key=lambda x: x[1].get("sharpe", 0))
  if bestSharpe[1].get("sharpe", 0) > 0:
    insights.append(f"リスク調整: {bestSharpe[0]} (シャープ {bestSharpe[1]['sharpe']:.2f}) が最も効率的")

  # 統計的信頼性の警告
  for name, m in metrics:
    trades = m.get("totalTrades", 0)
    winRate = m.get("winRate", 0)
    if trades < 10 and trades > 0:
      insights.append(f"注意: {name} は取引数{trades}で統計的信頼性が低い")
    elif winRate == 100 and trades < 20:
      insights.append(f"注意: {name} (勝率100%) だが取引数{trades}でサンプル不足の可能性")

  # PFが極端に高い場合
  for name, m in metrics:
    pf = m.get("profitFactor", 0)
    trades = m.get("totalTrades", 0)
    if pf > 10 and trades < 20:
      insights.append(f"注意: {name} PF {pf:.1f} は高すぎ -サンプル{trades}件に注意")

  return insights


def _generateScenarioInsights(summaries: list[dict], scenarios: dict) -> list[str]:
  """シナリオテスト結果から示唆を生成"""
  if not summaries:
    return []

  insights = []

  # 全シナリオ黒字の戦略
  allPositive = [s for s in summaries if all(v > 0 for v in s["perScenario"].values())]
  if allPositive:
    names = ", ".join(s["name"] for s in allPositive)
    insights.append(f"全シナリオ黒字: {names}")
  else:
    insights.append("全シナリオ黒字の戦略なし")

  # 下落耐性（bear + slow_bleed の平均損失が最小）
  downScenarios = ["bear", "slow_bleed", "bubble_burst"]
  downResistance = []
  for s in summaries:
    avgDown = sum(s["perScenario"].get(k, 0) for k in downScenarios if k in s["perScenario"]) / len(downScenarios)
    downResistance.append((s["name"], avgDown))
  bestDown = max(downResistance, key=lambda x: x[1])
  insights.append(f"下落耐性: {bestDown[0]} (下落3シナリオ平均 {bestDown[1]:+.1f}%)")

  # 最悪ケース
  for s in summaries:
    worstKey = min(s["perScenario"], key=s["perScenario"].get)
    worstVal = s["perScenario"][worstKey]
    if worstVal < -15:
      shortName = scenarios[worstKey]["name"] if worstKey in scenarios else worstKey
      insights.append(f"最悪ケース: {s['name']} ({shortName} {worstVal:+.1f}%)")

  # 総合推奨
  bestOverall = max(summaries, key=lambda s: s["expected"])
  insights.append(f"総合: {bestOverall['name']} (加重 {bestOverall['expected']:+.1f}%) が期待値最高")

  return insights


def printBenchAllocation(patterns: dict, allResults: dict, scenarios: dict,
                         realResult: dict = None, years: int = 0,
                         title: str = None) -> None:
  """配分パターン比較の統一出力"""
  label = title or "配分パターン比較"

  # シナリオ結果テーブル
  print(f"\n{'=' * 80}")
  print(f"  ALLOCATION  |  {label}  |  6シナリオ確率加重")
  print(f"{'=' * 80}")

  shortNames = {
    "bear": "bear", "range": "range", "crash_recovery": "crash",
    "slow_bleed": "bleed", "bubble_burst": "burst", "range_breakout": "brkout",
  }
  scenarioKeys = list(scenarios.keys())

  # ヘッダー
  header = f"\n  {'パターン':<16s} {'加重':>7s}"
  for sk in scenarioKeys:
    header += f" {shortNames.get(sk, sk[:6]):>7s}"
  print(header)
  print(f"  {'─' * (16 + 7 + len(scenarioKeys) * 8)}")

  summaries = []
  for pKey, pInfo in patterns.items():
    results = allResults[pKey]
    expectedReturn = sum(r["totalReturn"] * r["probability"] for r in results)
    expectedMdd = sum(r["mdd"] * r["probability"] for r in results)
    worstReturn = min(r["totalReturn"] for r in results)

    row = f"  {pInfo['label']:<16s} {expectedReturn:>+6.1f}%"
    perScenario = {}
    for sk in scenarioKeys:
      sr = next((r for r in results if r["scenarioKey"] == sk), None)
      ret = sr["totalReturn"] if sr else 0
      perScenario[sk] = ret
      row += f" {ret:>+6.1f}%"
    print(row)

    summaries.append({
      "label": pInfo["label"],
      "expected": expectedReturn,
      "expectedMdd": expectedMdd,
      "worst": worstReturn,
      "perScenario": perScenario,
    })

  # 実データ結果
  if realResult and "_period" in realResult:
    print(f"\n  ── 実データ ({realResult['_period']}) BTC {realResult['_btcChange']:+.1f}% ──")
    print(f"  {'パターン':<16s} {'リターン':>10s} {'MDD':>10s} {'リターン/MDD':>12s}")
    print(f"  {'─' * 50}")
    for pKey, pInfo in patterns.items():
      r = realResult[pKey]
      ratio = r["totalReturn"] / abs(r["mdd"]) if r["mdd"] != 0 else 0
      print(f"  {pInfo['label']:<16s} {r['totalReturn']:>+9.1f}% {r['mdd']:>+9.1f}% {ratio:>11.1f}")

  # 示唆
  insights = _generateAllocationInsights(summaries, realResult, patterns)
  if insights:
    print(f"\n  ── 示唆 ──")
    for line in insights:
      print(f"  - {line}")
  print()


def _generateAllocationInsights(summaries: list[dict], realResult: dict,
                                patterns: dict) -> list[str]:
  """配分パターン比較の示唆を生成"""
  if not summaries:
    return []

  insights = []

  # シナリオ期待値の比較
  best = max(summaries, key=lambda s: s["expected"])
  worst = min(summaries, key=lambda s: s["expected"])
  insights.append(f"期待リターン最高: {best['label']} ({best['expected']:+.1f}%)")
  if best["label"] != worst["label"]:
    diff = best["expected"] - worst["expected"]
    insights.append(f"最高-最低の差: {diff:.1f}pt ({best['label']} vs {worst['label']})")

  # MDD比較
  bestMdd = max(summaries, key=lambda s: s["expectedMdd"])  # 最も浅いMDD
  insights.append(f"期待MDD最良: {bestMdd['label']} ({bestMdd['expectedMdd']:+.1f}%)")

  # 全シナリオ黒字
  allPositive = [s for s in summaries if all(v > 0 for v in s["perScenario"].values())]
  if allPositive:
    names = ", ".join(s["label"] for s in allPositive)
    insights.append(f"全シナリオ黒字: {names}")

  # 実データがあれば
  if realResult and "_period" in realResult:
    realBest = max(
      ((pKey, realResult[pKey]) for pKey in patterns if pKey in realResult and isinstance(realResult[pKey], dict)),
      key=lambda x: x[1]["totalReturn"],
    )
    pLabel = patterns[realBest[0]]["label"]
    r = realBest[1]
    ratio = r["totalReturn"] / abs(r["mdd"]) if r["mdd"] != 0 else 0
    insights.append(f"実データ推奨: {pLabel} (リターン/MDD {ratio:.1f})")

  return insights


# ---------------------------------------------------------------------------
# bench — 共通保存
# ---------------------------------------------------------------------------

def _benchFileName(benchType: str, strategies: list[str], symbol: str,
                   interval: str, years: int, sl: float = None, tp: float = None) -> str:
  """条件からベンチ結果のファイル名を決定（同条件は上書き）"""
  parts = [benchType, "+".join(sorted(strategies)), symbol, interval, f"{years}y"]
  if sl is not None:
    parts.append(f"sl{sl}")
  if tp is not None:
    parts.append(f"tp{tp}")
  return "_".join(parts) + ".json"


def saveBenchResult(benchType: str, strategies: list[str], symbol: str,
                    interval: str, years: int, sl: float = None, tp: float = None,
                    results: dict = None, strategyVersions: dict = None,
                    changelogs: dict = None) -> Path:
  """ベンチ結果を共通フォーマットで保存（同条件は上書き）"""
  BENCH_DIR.mkdir(parents=True, exist_ok=True)
  filename = _benchFileName(benchType, strategies, symbol, interval, years, sl, tp)
  outPath = BENCH_DIR / filename

  data = {
    "benchType": benchType,
    "strategies": strategies,
    "symbol": symbol,
    "interval": interval,
    "years": years,
    "sl": sl,
    "tp": tp,
    "strategyVersions": strategyVersions or {},
    "changelogs": changelogs or {},
    "results": results or {},
    "savedAt": datetime.now().isoformat(),
  }

  outPath.write_text(
    json.dumps(data, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )
  print(f"  ベンチ結果保存: {outPath}")
  return outPath


def saveLiveState(strategyName: str, symbol: str, state: dict) -> Path:
  """ライブシミュレーションの状態をJSONに書き出し"""
  LIVE_DIR.mkdir(parents=True, exist_ok=True)
  filename = f"{strategyName}_{symbol}.json".replace(" ", "_").replace("/", "-")
  outPath = LIVE_DIR / filename

  state["updatedAt"] = datetime.now().isoformat()
  outPath.write_text(
    json.dumps(state, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )
  return outPath
