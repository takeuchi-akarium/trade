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
