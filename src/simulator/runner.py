"""
統一シミュレーション CLI

使い方:
  python src/simulator/runner.py list
  python src/simulator/runner.py run --strategy rsi --symbol BTCUSDT --interval 1d
  python src/simulator/runner.py compare --strategies rsi,bb,ema --symbol BTCUSDT
  python src/simulator/runner.py live --strategy rsi --symbol BTCUSDT --interval 5m
  python src/simulator/runner.py bench --type backtest --strategies all --years 3
  python src/simulator/runner.py bench --type scenario --strategies bb,ema_don --sl 5.0
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# src/ をパスに追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def cmdList(args):
  """登録済み戦略の一覧を表示"""
  import strategies
  from strategies.registry import listStrategies

  strats = listStrategies()
  print(f"\n  登録済み戦略: {len(strats)}件\n")
  print(f"  {'名前':<20s} {'カテゴリ':<12s} {'説明'}")
  print(f"  {'-' * 60}")
  for s in strats:
    print(f"  {s.name:<20s} {s.category:<12s} {s.description}")
  print()


def cmdRun(args):
  """単一戦略のバックテストを実行"""
  import strategies
  from strategies.registry import getStrategy
  from simulator.metrics import ensureMetrics
  from simulator.report import printResult, saveResult

  strategy = getStrategy(args.strategy)
  print(f"\n  戦略: {strategy.description}")
  print(f"  銘柄: {args.symbol}  間隔: {args.interval}")
  print(f"  データ取得中...")

  data = strategy.fetchData(
    symbol=args.symbol, interval=args.interval,
    years=args.years)

  print(f"  取得完了: {len(data)}行")
  print(f"  バックテスト実行中...")

  result = strategy.backtest(
    data,
    symbol=args.symbol,
    interval=args.interval,
    capital=args.capital,
    fee=args.fee,
    sl=args.sl,
    tp=args.tp,
  )

  # メトリクス補完
  initialCapital = result.equity.iloc[0] if len(result.equity) > 0 else args.capital
  result.metrics = ensureMetrics(result.metrics, result.trades, result.equity, initialCapital)

  printResult(result)
  saveResult(result)
  print(f"\n  ブラウザで確認: http://localhost:5000/simulations")


def cmdCompare(args):
  """複数戦略の比較バックテスト"""
  import strategies
  from strategies.registry import getStrategy
  from simulator.metrics import ensureMetrics
  from simulator.report import printResult, saveCompare

  strategyKeys = [s.strip() for s in args.strategies.split(",")]
  results = []
  dataCache = {}  # 同じfetchDataソースのデータを使い回す

  for key in strategyKeys:
    strategy = getStrategy(key)

    # 戦略クラス名をキーにキャッシュ（同じクラスなら同じデータ）
    fetchKey = (strategy.__class__.__name__, args.symbol, args.interval, args.years)
    if fetchKey in dataCache:
      data = dataCache[fetchKey]
      print(f"\n  [{key}] キャッシュ済みデータを使用 ({len(data)}行)")
    else:
      print(f"\n  [{key}] データ取得中...")
      data = strategy.fetchData(
        symbol=args.symbol, interval=args.interval,
        years=args.years)
      dataCache[fetchKey] = data
      print(f"  [{key}] 取得完了 ({len(data)}行)")

    print(f"  [{key}] バックテスト実行中...")

    result = strategy.backtest(
      data,
      symbol=args.symbol,
      interval=args.interval,
      capital=args.capital,
      fee=args.fee,
      sl=args.sl,
      tp=args.tp,
    )

    initialCapital = result.equity.iloc[0] if len(result.equity) > 0 else args.capital
    result.metrics = ensureMetrics(result.metrics, result.trades, result.equity, initialCapital)
    results.append(result)
    printResult(result)

  saveCompare(results)
  print(f"\n  ブラウザで確認: http://localhost:5000/simulations")


# ---------------------------------------------------------------------------
# bench — 統一ベンチマーク
# ---------------------------------------------------------------------------

def _resolveStrategies(strategiesArg: str) -> list:
  """戦略指定を解決: 戦略名カンマ区切り / all / カテゴリ名"""
  import strategies
  from strategies.registry import listStrategies

  allStrats = listStrategies()
  categories = {s.category for s in allStrats}

  if strategiesArg == "all":
    return allStrats

  if strategiesArg in categories:
    return [s for s in allStrats if s.category == strategiesArg]

  # カンマ区切りの戦略名
  from strategies.registry import getStrategy
  keys = [k.strip() for k in strategiesArg.split(",")]
  return [getStrategy(k) for k in keys]


def cmdBench(args):
  """統一ベンチマーク — バックテスト/シナリオ/配分比較で戦略を評価"""
  if args.type == "allocation":
    print(f"\n  bench (allocation)  DART配分パターン比較")
    _benchAllocation(args)
    return

  strategyList = _resolveStrategies(args.strategies)
  strategyNames = [s.name for s in strategyList]

  if not strategyList:
    print("  対象戦略がありません")
    return

  print(f"\n  bench ({args.type})  対象: {', '.join(strategyNames)}")

  if args.type == "backtest":
    _benchBacktest(args, strategyList)
  elif args.type == "scenario":
    _benchScenario(args, strategyNames)
  else:
    print(f"  不明なタイプ: {args.type} (backtest / scenario / allocation)")


def _benchBacktest(args, strategyList):
  """バックテストベンチ"""
  from simulator.metrics import ensureMetrics
  from simulator.report import printBenchBacktest, saveCompare

  results = []
  dataCache = {}

  for strategy in strategyList:
    key = strategy.name
    fetchKey = (strategy.__class__.__name__, args.symbol, args.interval, args.years)

    if fetchKey in dataCache:
      data = dataCache[fetchKey]
    else:
      print(f"  [{key}] データ取得中...")
      try:
        data = strategy.fetchData(
          symbol=args.symbol, interval=args.interval,
          years=args.years)
        dataCache[fetchKey] = data
      except Exception as e:
        print(f"  [{key}] スキップ: {e}")
        continue

    print(f"  [{key}] バックテスト実行中... ({len(data)}行)")
    try:
      result = strategy.backtest(
        data,
        symbol=args.symbol,
        interval=args.interval,
        capital=args.capital,
        fee=args.fee,
        sl=args.sl,
        tp=args.tp,
      )
      initialCapital = result.equity.iloc[0] if len(result.equity) > 0 else args.capital
      result.metrics = ensureMetrics(result.metrics, result.trades, result.equity, initialCapital)
      results.append(result)
    except Exception as e:
      print(f"  [{key}] スキップ: {e}")
      continue

  if results:
    printBenchBacktest(results, args.symbol, args.interval, args.years, args.sl, args.tp)
    saveCompare(results)

    # bench共通保存
    from simulator.report import saveBenchResult
    stratNames = [r.strategyName for r in results]
    versions = {r.strategyName: next(s.version for s in strategyList if s.name == r.strategyName) for r in results}
    saveBenchResult(
      "backtest", stratNames, args.symbol, args.interval, args.years,
      sl=args.sl, tp=args.tp,
      results={r.strategyName: r.metrics for r in results},
      strategyVersions=versions,
    )


def _benchScenario(args, strategyNames):
  """シナリオベンチ"""
  from simulator.scenario import SCENARIOS, runScenario
  from simulator.report import printBenchScenario

  scenarioResults = []
  for sKey in SCENARIOS:
    for name in strategyNames:
      print(f"  [{name}] {SCENARIOS[sKey]['name']}...")
      try:
        r = runScenario(name, sKey, sl=args.sl)
        scenarioResults.append(r)
      except Exception as e:
        print(f"  [{name}] {sKey} スキップ: {e}")

  if scenarioResults:
    printBenchScenario(scenarioResults, strategyNames, SCENARIOS, args.sl)

    # bench共通保存
    from simulator.report import saveBenchResult
    from strategies.registry import getStrategy
    versions = {}
    for name in strategyNames:
      try:
        versions[name] = getStrategy(name).version
      except KeyError:
        pass

    # 戦略ごとにシナリオ結果を整理
    resultsByStrategy = {}
    for name in strategyNames:
      stratResults = [r for r in scenarioResults if r["strategy"] == name]
      expectedReturn = sum(
        r["metrics"]["totalReturn"] * SCENARIOS[r["scenarioKey"]]["probability"]
        for r in stratResults
      )
      perScenario = {r["scenarioKey"]: r["metrics"]["totalReturn"] for r in stratResults}
      resultsByStrategy[name] = {
        "expectedReturn": round(expectedReturn, 2),
        "perScenario": perScenario,
      }

    saveBenchResult(
      "scenario", strategyNames, args.symbol, args.interval, args.years,
      sl=args.sl,
      results=resultsByStrategy,
      strategyVersions=versions,
    )


def _runPortfolioBacktest(data, strategyNames, capital, feePct, weights):
  """任意のN戦略でポートフォリオバックテストを実行"""
  from strategies.registry import getStrategy

  # 各戦略のequity curveを取得
  returns = {}
  for name in strategyNames:
    strategy = getStrategy(name)
    result = strategy.backtest(data.copy(), symbol="PORTFOLIO", interval="1d",
                               capital=capital, fee=feePct)
    eq = result.equity
    returns[name] = eq.pct_change().fillna(0)

  # ポートフォリオequityを構築
  equity = capital
  equityList = []

  for i in range(len(data)):
    portfolioReturn = sum(weights.get(name, 0) * returns[name].iloc[i] for name in strategyNames)
    equity *= (1 + portfolioReturn)
    equityList.append(equity)

  eqSeries = pd.Series(equityList, index=data.index)
  finalValue = equityList[-1] if equityList else capital
  totalReturn = (finalValue - capital) / capital * 100
  peak = eqSeries.expanding().max()
  dd = (eqSeries - peak) / peak * 100
  mdd = float(dd.min())

  return {
    "totalReturn": totalReturn,
    "finalValue": finalValue,
    "mdd": mdd,
  }


def _generateAllocationPatterns(strategyNames):
  """N戦略から配分パターンを自動生成"""
  n = len(strategyNames)
  patterns = {}

  # 等配分
  eqWeight = round(1.0 / n, 2)
  patterns["equal"] = {
    "label": f"等配分 (1/{n})",
    "weights": {name: eqWeight for name in strategyNames},
  }

  # 各戦略単独
  for name in strategyNames:
    patterns[f"solo_{name}"] = {
      "label": f"{name}単独",
      "weights": {name: 1.0, **{other: 0.0 for other in strategyNames if other != name}},
    }

  return patterns


def _benchAllocation(args):
  """汎用配分パターン比較ベンチ"""
  import strategies
  from strategies.registry import getStrategy
  from simulator.scenario import SCENARIOS
  from simulator.report import printBenchAllocation

  # --strategies が指定されていれば汎用モード、なければDART
  isDart = (args.strategies == "all")
  if isDart:
    strategyNames = ["bb", "ema_don", "bb_ls"]
  else:
    strategyNames = [s.strip() for s in args.strategies.split(",")]

  print(f"  対象戦略: {', '.join(strategyNames)}")

  # DART用: scenario.pyの既存ロジックを使用（高速・リバランスコスト込み）
  if isDart:
    from simulator.scenario import (
      ALLOCATION_PATTERNS, runDynamicWeight,
      _runBacktestOnData, _prepareBacktestData,
    )
    patterns = ALLOCATION_PATTERNS
    allResults = {pKey: [] for pKey in patterns}

    print("  シナリオ評価中...")
    for sKey, sInfo in SCENARIOS.items():
      precomputed = _prepareBacktestData(sKey, args.capital, args.fee, 50)
      for pKey, pInfo in patterns.items():
        if pInfo["type"] == "gradient":
          result = runDynamicWeight(sKey, precomputed=precomputed,
                                   gradientLevels=pInfo["levels"],
                                   nanDefault=pInfo.get("nanDefault"))
        else:
          result = runDynamicWeight(sKey, precomputed=precomputed,
                                   weights=pInfo["weights"])
        allResults[pKey].append({
          "scenarioKey": sKey,
          "probability": sInfo["probability"],
          **result,
        })

    realResult = {}
    if args.years > 0:
      print(f"  実データ評価中 ({args.years}年)...")
      strategy = getStrategy("bb")
      data = strategy.fetchData(symbol=args.symbol, interval="1d", years=args.years)
      precomputed = _runBacktestOnData(data, args.capital, args.fee, 50)

      for pKey, pInfo in patterns.items():
        if pInfo["type"] == "gradient":
          result = runDynamicWeight(precomputed=precomputed,
                                   gradientLevels=pInfo["levels"],
                                   nanDefault=pInfo.get("nanDefault"))
        else:
          result = runDynamicWeight(precomputed=precomputed,
                                   weights=pInfo["weights"])
        realResult[pKey] = result
      realResult["_period"] = f"{data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')}"
      realResult["_btcChange"] = (data['close'].iloc[-1] - data['close'].iloc[0]) / data['close'].iloc[0] * 100

    printBenchAllocation(patterns, allResults, SCENARIOS, realResult, args.years,
                         title="DART配分パターン比較")

    # bench共通保存
    from simulator.report import saveBenchResult
    from strategies.registry import getStrategy as _gs
    versions = {n: _gs(n).version for n in strategyNames}
    allocResults = {}
    for pKey, pInfo in patterns.items():
      results = allResults[pKey]
      expected = sum(r["totalReturn"] * r["probability"] for r in results)
      allocResults[pInfo["label"]] = {
        "expectedReturn": round(expected, 2),
        "realReturn": round(realResult[pKey]["totalReturn"], 2) if pKey in realResult and isinstance(realResult.get(pKey), dict) else None,
        "realMdd": round(realResult[pKey]["mdd"], 2) if pKey in realResult and isinstance(realResult.get(pKey), dict) else None,
      }
    saveBenchResult(
      "allocation", strategyNames, args.symbol, "1d", args.years,
      results=allocResults, strategyVersions=versions,
    )
    return

  # 汎用モード: 任意のN戦略の配分比較
  patterns = _generateAllocationPatterns(strategyNames)
  allResults = {pKey: [] for pKey in patterns}

  # シナリオ評価
  print("  シナリオ評価中...")
  for sKey, sInfo in SCENARIOS.items():
    data = sInfo["fn"]()
    for pKey, pInfo in patterns.items():
      result = _runPortfolioBacktest(
        data, strategyNames, args.capital, args.fee, pInfo["weights"])
      result["scenario"] = sInfo["name"]
      result["scenarioKey"] = sKey
      allResults[pKey].append({
        "scenarioKey": sKey,
        "probability": sInfo["probability"],
        **result,
      })

  # 実データ評価
  realResult = {}
  if args.years > 0:
    print(f"  実データ評価中 ({args.years}年)...")
    strategy = getStrategy(strategyNames[0])
    data = strategy.fetchData(symbol=args.symbol, interval="1d", years=args.years)

    for pKey, pInfo in patterns.items():
      result = _runPortfolioBacktest(
        data, strategyNames, args.capital, args.fee, pInfo["weights"])
      realResult[pKey] = result
    realResult["_period"] = f"{data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')}"
    realResult["_btcChange"] = (data['close'].iloc[-1] - data['close'].iloc[0]) / data['close'].iloc[0] * 100

  title = f"{'+'.join(strategyNames)} 配分比較"
  printBenchAllocation(patterns, allResults, SCENARIOS, realResult, args.years,
                       title=title)

  # bench共通保存
  from simulator.report import saveBenchResult
  from strategies.registry import getStrategy as _gs
  versions = {}
  for n in strategyNames:
    try:
      versions[n] = _gs(n).version
    except KeyError:
      pass
  allocResults = {}
  for pKey, pInfo in patterns.items():
    results = allResults[pKey]
    expected = sum(r["totalReturn"] * r["probability"] for r in results)
    allocResults[pInfo["label"]] = {
      "expectedReturn": round(expected, 2),
      "realReturn": round(realResult[pKey]["totalReturn"], 2) if pKey in realResult and isinstance(realResult.get(pKey), dict) else None,
      "realMdd": round(realResult[pKey]["mdd"], 2) if pKey in realResult and isinstance(realResult.get(pKey), dict) else None,
    }
  saveBenchResult(
    "allocation", strategyNames, args.symbol, "1d", args.years,
    results=allocResults, strategyVersions=versions,
  )


# ---------------------------------------------------------------------------
# live — リアルタイムペーパートレード
# ---------------------------------------------------------------------------

POLL_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
LOOKBACK = 200


def _liveStateFile(strategyName: str, symbol: str) -> Path:
  d = Path(__file__).resolve().parent.parent.parent / "data" / "simulations" / "live"
  d.mkdir(parents=True, exist_ok=True)
  return d / f"{strategyName}_{symbol}.json".replace(" ", "_")


def _loadLiveState(strategyName: str, symbol: str, initialCapital: float) -> dict:
  f = _liveStateFile(strategyName, symbol)
  if f.exists():
    return json.loads(f.read_text(encoding="utf-8"))
  return {
    "strategyName": strategyName,
    "symbol": symbol,
    "initialCapital": initialCapital,
    "capital": initialCapital,
    "holding": 0.0,
    "entryPrice": 0.0,
    "totalTrades": 0,
    "wins": 0,
    "losses": 0,
    "totalPnl": 0.0,
    "peakCapital": initialCapital,
    "lastPrice": 0.0,
    "lastSignal": 0,
    "equityHistory": [],
  }


def _saveLiveState(state: dict) -> None:
  state["updatedAt"] = datetime.now().isoformat()
  f = _liveStateFile(state["strategyName"], state["symbol"])
  f.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _appendEquity(state: dict, price: float) -> None:
  equity = state["capital"] if state["holding"] == 0 else state["holding"] * price
  state["equityHistory"].append({
    "date": datetime.now().isoformat(),
    "value": round(equity, 2),
  })
  # 最大1000点に制限
  if len(state["equityHistory"]) > 1000:
    state["equityHistory"] = state["equityHistory"][-1000:]


def cmdLive(args):
  """リアルタイムペーパートレード"""
  import strategies
  from strategies.registry import getStrategy

  strategy = getStrategy(args.strategy)
  symbol = args.symbol
  interval = args.interval
  feeRate = args.fee / 100
  pollSec = POLL_INTERVALS.get(interval, 300)

  state = _loadLiveState(strategy.name, symbol, args.capital)
  state["interval"] = interval
  # 初回起動時のみ資金を設定
  if args.capital and state["capital"] == state["initialCapital"] and state["totalTrades"] == 0:
    state["capital"] = args.capital
    state["initialCapital"] = args.capital
    state["peakCapital"] = args.capital

  print(f"リアルタイムシミュレーション開始")
  print(f"  銘柄: {symbol}  戦略: {strategy.description}  間隔: {interval} ({pollSec}秒)")
  print(f"  初期資金: {state['capital']:,.0f}  手数料: {args.fee}%")
  if args.sl:
    print(f"  ストップロス: {args.sl}%")
  if args.tp:
    print(f"  テイクプロフィット: {args.tp}%")
  print(f"  ブラウザで確認: http://localhost:5000/simulations")
  print(f"  Ctrl+C で停止\n")

  latestPrice = 0.0

  try:
    while True:
      try:
        data = strategy.fetchData(symbol=symbol, interval=interval, years=1)
        data = data.tail(LOOKBACK)
        # 最終行は未確定足の可能性があるため除外して確定足のみでシグナル判定
        data = data.iloc[:-1]

        dfS = strategy.generateSignals(data)
        latestSignal = int(dfS["signal"].iloc[-1])
        latestPrice = float(dfS["close"].iloc[-1])
        now = datetime.now()

        state["lastPrice"] = latestPrice
        state["lastSignal"] = latestSignal

        # SL/TP判定
        if state["holding"] > 0:
          pnlPct = (latestPrice - state["entryPrice"]) / state["entryPrice"] * 100
          slHit = args.sl is not None and pnlPct <= -args.sl
          tpHit = args.tp is not None and pnlPct >= args.tp

          if slHit or tpHit:
            proceeds = state["holding"] * latestPrice
            fee = proceeds * feeRate
            state["capital"] = proceeds - fee
            pnl = latestPrice - state["entryPrice"]
            state["totalTrades"] += 1
            if pnl > 0:
              state["wins"] += 1
            else:
              state["losses"] += 1
            state["totalPnl"] += pnl
            state["holding"] = 0
            state["entryPrice"] = 0
            state["peakCapital"] = max(state["peakCapital"], state["capital"])
            reason = "SL" if slHit else "TP"
            print(f"\n  {reason}発動 @ {latestPrice:,.0f}  損益: {pnl:+,.0f}")
            latestSignal = 0

        # 売りシグナル
        if latestSignal == -1 and state["holding"] > 0:
          proceeds = state["holding"] * latestPrice
          fee = proceeds * feeRate
          state["capital"] = proceeds - fee
          pnl = latestPrice - state["entryPrice"]
          state["totalTrades"] += 1
          if pnl > 0:
            state["wins"] += 1
          else:
            state["losses"] += 1
          state["totalPnl"] += pnl
          state["holding"] = 0
          state["entryPrice"] = 0
          state["peakCapital"] = max(state["peakCapital"], state["capital"])
          print(f"\n  売り @ {latestPrice:,.0f}  損益: {pnl:+,.0f}")

        # 買いシグナル
        elif latestSignal == 1 and state["holding"] == 0:
          fee = state["capital"] * feeRate
          investable = state["capital"] - fee
          state["holding"] = investable / latestPrice
          state["entryPrice"] = latestPrice
          state["capital"] = 0
          print(f"\n  買い @ {latestPrice:,.0f}  数量: {state['holding']:.6f}")

        # 状態保存 (ブラウザから見える)
        _appendEquity(state, latestPrice)
        _saveLiveState(state)

        # ターミナル表示
        equity = state["capital"] if state["holding"] == 0 else state["holding"] * latestPrice
        totalReturn = (equity / state["initialCapital"] - 1) * 100
        nTrades = state["totalTrades"]
        winRate = state["wins"] / nTrades * 100 if nTrades > 0 else 0
        dd = (equity - state["peakCapital"]) / state["peakCapital"] * 100 if state["peakCapital"] > 0 else 0
        signalStr = {1: "BUY", -1: "SELL", 0: "HOLD"}.get(latestSignal, "")
        posStr = f"保���中 @ {state['entryPrice']:,.0f}" if state["holding"] > 0 else "ノーポジ"

        print(f"\r  [{now.strftime('%H:%M:%S')}] ${latestPrice:>10,.0f}  {signalStr:<5s}  {posStr:<22s}  "
              f"資産: {equity:>10,.0f}  {totalReturn:>+6.1f}%  "
              f"勝率: {winRate:>4.0f}% ({nTrades})  DD: {dd:>5.1f}%", end="", flush=True)

      except Exception as e:
        print(f"\n  エラー: {e}")

      time.sleep(pollSec)

  except KeyboardInterrupt:
    equity = state["capital"] if state["holding"] == 0 else state["holding"] * latestPrice
    nTrades = state["totalTrades"]
    winRate = state["wins"] / nTrades * 100 if nTrades > 0 else 0

    print(f"\n\n{'=' * 50}")
    print(f"  シミュレーション終了")
    print(f"{'=' * 50}")
    print(f"  最終資産    : {equity:>12,.0f}")
    print(f"  総損益      : {state['totalPnl']:>+12,.0f}")
    print(f"  取引回数    : {nTrades:>12d}")
    print(f"  勝率        : {winRate:>11.1f}%")
    _saveLiveState(state)
    print(f"\n  状態保存済み (ブラウザで確認: http://localhost:5000/simulations)")


def main():
  parser = argparse.ArgumentParser(description="統一シミュレーション CLI")
  sub = parser.add_subparsers(dest="command", required=True)

  # list
  sub.add_parser("list", help="登録済み戦略の一覧")

  # run
  runParser = sub.add_parser("run", help="単一戦略のバックテスト")
  runParser.add_argument("--strategy", required=True, help="戦略名")
  runParser.add_argument("--symbol", default="BTCUSDT", help="銘柄")
  runParser.add_argument("--interval", default="1d", help="タイムフレーム")
  runParser.add_argument("--years", type=int, default=1, help="取得年数")
  runParser.add_argument("--capital", type=float, default=100_000, help="初期資金")
  runParser.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  runParser.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  runParser.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")
  runParser.add_argument("--no-browser", action="store_true", help="ブラウザ自動オープンを抑制")

  # compare
  cmpParser = sub.add_parser("compare", help="複数戦略の比較")
  cmpParser.add_argument("--strategies", required=True, help="戦略名 (カンマ区切り)")
  cmpParser.add_argument("--symbol", default="BTCUSDT", help="銘柄")
  cmpParser.add_argument("--interval", default="1d", help="タイムフレーム")
  cmpParser.add_argument("--years", type=int, default=1, help="取得年数")
  cmpParser.add_argument("--capital", type=float, default=100_000, help="初期資金")
  cmpParser.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  cmpParser.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  cmpParser.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")
  cmpParser.add_argument("--no-browser", action="store_true", help="ブラウザ自動オープンを抑制")

  # bench
  benchParser = sub.add_parser("bench", help="統一ベンチマーク（バックテスト/シナリオ）")
  benchParser.add_argument("--type", default="backtest", choices=["backtest", "scenario", "allocation"], help="ベンチ種類")
  benchParser.add_argument("--strategies", default="all", help="戦略名 (カンマ区切り / all / カテゴリ名)")
  benchParser.add_argument("--symbol", default="BTCUSDT", help="銘柄")
  benchParser.add_argument("--interval", default="1d", help="タイムフレーム")
  benchParser.add_argument("--years", type=int, default=1, help="取得年数")
  benchParser.add_argument("--capital", type=float, default=100_000, help="初期資金")
  benchParser.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  benchParser.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  benchParser.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")

  # live
  liveParser = sub.add_parser("live", help="リアルタイムペーパートレード")
  liveParser.add_argument("--strategy", required=True, help="戦略名")
  liveParser.add_argument("--symbol", default="BTCUSDT", help="銘柄")
  liveParser.add_argument("--interval", default="5m", help="タイムフレーム (1m,5m,15m,1h)")
  liveParser.add_argument("--capital", type=float, default=100_000, help="初期資金 (初回のみ有効)")
  liveParser.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  liveParser.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  liveParser.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")

  args = parser.parse_args()

  if args.command == "list":
    cmdList(args)
  elif args.command == "run":
    cmdRun(args)
  elif args.command == "compare":
    cmdCompare(args)
  elif args.command == "bench":
    cmdBench(args)
  elif args.command == "live":
    cmdLive(args)


if __name__ == "__main__":
  main()
