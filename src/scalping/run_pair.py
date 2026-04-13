"""
ペアトレード（US100買い × US30売り）バックテスト CLI

使用例:
  python src/scalping/run_pair.py --strategy bb
  python src/scalping/run_pair.py --strategy ema
  python src/scalping/run_pair.py --strategy bb --period 30 --entry-std 1.5
  python src/scalping/run_pair.py --compare
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

# プロジェクトルートをパスに追加
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from scalping.pair_strategy import calcSpread, calcPairSignals, PAIR_STRATEGIES
from scalping.pair_backtest import (
  runPairBacktest, calcPairMetrics, printPairMetrics, plotPairResult,
)


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def fetchIndexData(period: str = "2y") -> tuple[pd.DataFrame, pd.DataFrame]:
  """yfinanceからナスダックとダウの日足データを取得"""
  print(f"yfinanceから ^IXIC (NASDAQ) を取得中...")
  nasdaq = yf.Ticker("^IXIC")
  dfNasdaq = nasdaq.history(period=period, interval="1d")
  dfNasdaq.columns = [c.lower() for c in dfNasdaq.columns]
  for col in ("dividends", "stock splits", "capital gains"):
    dfNasdaq = dfNasdaq.drop(columns=[col], errors="ignore")

  print(f"yfinanceから ^DJI (DOW) を取得中...")
  dow = yf.Ticker("^DJI")
  dfDow = dow.history(period=period, interval="1d")
  dfDow.columns = [c.lower() for c in dfDow.columns]
  for col in ("dividends", "stock splits", "capital gains"):
    dfDow = dfDow.drop(columns=[col], errors="ignore")

  print(f"  NASDAQ: {len(dfNasdaq)}本  DOW: {len(dfDow)}本")
  return dfNasdaq, dfDow


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
  parser = argparse.ArgumentParser(
    description="US100買い × US30売り ペアトレード バックテスト"
  )
  parser.add_argument("--strategy", default="bb",
                      help=f"戦略キー ({', '.join(PAIR_STRATEGIES.keys())})")
  parser.add_argument("--period", default="2y",
                      help="データ取得期間 (1y, 2y, 5y, max)")
  parser.add_argument("--capital", type=float, default=1_000_000,
                      help="初期資金 (デフォルト: 1,000,000)")
  parser.add_argument("--fee", type=float, default=0.1,
                      help="手数料 (%%)")
  parser.add_argument("--sl", type=float, default=None,
                      help="ストップロス (%%)")
  parser.add_argument("--tp", type=float, default=None,
                      help="テイクプロフィット (%%)")
  parser.add_argument("--nasdaq-lots", type=float, default=10,
                      help="ナスダックロット数 (デフォルト: 10)")
  parser.add_argument("--dow-lots", type=float, default=4,
                      help="ダウロット数 (デフォルト: 4)")
  parser.add_argument("--compare", action="store_true",
                      help="全戦略比較モード")

  # BB固有パラメータ
  parser.add_argument("--bb-period", type=int, default=20)
  parser.add_argument("--entry-std", type=float, default=2.0)
  parser.add_argument("--exit-std", type=float, default=0.0)

  # EMA固有パラメータ
  parser.add_argument("--ema-short", type=int, default=5)
  parser.add_argument("--ema-long", type=int, default=20)

  args = parser.parse_args()

  # データ取得
  dfNasdaq, dfDow = fetchIndexData(args.period)

  # スプレッド計算
  dfSpread = calcSpread(dfNasdaq, dfDow, args.nasdaq_lots, args.dow_lots)
  print(f"  スプレッドデータ: {len(dfSpread)}本  "
        f"期間: {dfSpread.index[0].strftime('%Y-%m-%d')} 〜 "
        f"{dfSpread.index[-1].strftime('%Y-%m-%d')}")

  if args.compare:
    # 全戦略比較
    print(f"\n{'=' * 70}")
    print(f"  全戦略比較: US100({args.nasdaq_lots}lot) × US30({args.dow_lots}lot)")
    print(f"  初期資金: {args.capital:,.0f}  手数料: {args.fee}%")
    print(f"{'=' * 70}")

    for key, entry in PAIR_STRATEGIES.items():
      dfS = calcPairSignals(dfSpread, key)
      trades, equity = runPairBacktest(
        dfS, args.capital, args.fee, args.sl, args.tp,
        args.nasdaq_lots, args.dow_lots,
      )
      metrics = calcPairMetrics(trades, equity, args.capital)
      printPairMetrics(metrics)
      plotPairResult(dfS, trades, equity, args.capital, entry["name"])

  else:
    # 単一戦略
    if args.strategy not in PAIR_STRATEGIES:
      print(f"不明な戦略: {args.strategy}  選択肢: {', '.join(PAIR_STRATEGIES.keys())}")
      return

    # 戦略固有パラメータを渡す
    kwargs = {}
    if args.strategy == "bb":
      kwargs = {"period": args.bb_period, "entryStd": args.entry_std, "exitStd": args.exit_std}
    elif args.strategy == "ema":
      kwargs = {"short": args.ema_short, "long": args.ema_long}

    dfS = calcPairSignals(dfSpread, args.strategy, **kwargs)
    trades, equity = runPairBacktest(
      dfS, args.capital, args.fee, args.sl, args.tp,
      args.nasdaq_lots, args.dow_lots,
    )
    metrics = calcPairMetrics(trades, equity, args.capital)
    printPairMetrics(metrics)

    strategyName = PAIR_STRATEGIES[args.strategy]["name"]
    plotPairResult(dfS, trades, equity, args.capital, strategyName)

    # x-trade.jpとの比較コメント
    print(f"\n{'─' * 60}")
    print(f"  【参考】x-trade.jp 実績（2024/10〜2025/11）")
    print(f"    勝率: 86.4%  PF: 2.43  トレード: 132件")
    print(f"{'─' * 60}")


if __name__ == "__main__":
  main()
