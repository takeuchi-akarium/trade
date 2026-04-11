"""
バックテスト実行

全期間のバックテストを実行し、論文 Table 2 の結果と比較する。
コマンドラインから直接実行可能:
  python src/leadlag/backtest.py
"""

import sys
from pathlib import Path

# src/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from leadlag.constants import (
  US_TICKERS, JP_TICKERS, ROLLING_WINDOW, LAMBDA_REG,
  NUM_FACTORS, QUANTILE_CUTOFF, C_FULL_START, C_FULL_END,
)
from leadlag.fetch_data import fetchAllPrices, calcCcReturns, calcOcReturns
from leadlag.calendar_align import alignReturns
from leadlag.signal_generator import generateSignals, generateSignalsWithFeedback, generateSignalsEnhanced
from leadlag.portfolio import constructPortfolio
from leadlag.metrics import calcMetrics


def runBacktest(
  backtestStart="2015-01-01",
  backtestEnd="2025-12-31",
  lam=LAMBDA_REG,
  k=NUM_FACTORS,
  window=ROLLING_WINDOW,
  q=QUANTILE_CUTOFF,
):
  """
  全期間バックテストを実行する。

  Returns:
    dict: {metrics, portfolio, signals}
  """
  print("=== 日米リードラグ戦略 バックテスト ===")
  print(f"パラメータ: L={window}, λ={lam}, K={k}, q={q}")
  print(f"C_full期間: {C_FULL_START} ~ {C_FULL_END}")
  print(f"バックテスト: {backtestStart} ~ {backtestEnd}")
  print()

  # Step 1: データ取得
  print("[1/5] データ取得中...")
  usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end=backtestEnd)
  print(f"  US: {len(usPrices)}行, JP: {len(jpPrices)}行")

  # Step 2: リターン計算
  print("[2/5] リターン計算中...")
  usRetCc = calcCcReturns(usPrices, US_TICKERS)
  jpRetCc = calcCcReturns(jpPrices, JP_TICKERS)
  jpRetOc = calcOcReturns(jpPrices, JP_TICKERS)
  print(f"  US CC: {len(usRetCc)}行, JP CC: {len(jpRetCc)}行, JP OC: {len(jpRetOc)}行")

  # Step 3: カレンダーアラインメント
  print("[3/5] 日米カレンダー アラインメント中...")
  aligned = alignReturns(usRetCc, jpRetCc, jpRetOc)
  print(f"  アラインメント済み: {len(aligned)}行")

  # Step 4: シグナル生成
  print("[4/5] シグナル生成中 (ウォークフォワード)...")
  signals = generateSignals(aligned, lam=lam, k=k, window=window)
  # バックテスト期間にフィルタ
  signals = signals[(signals.index >= backtestStart) & (signals.index <= backtestEnd)]
  print(f"  シグナル: {len(signals)}行")

  # Step 5: ポートフォリオ構築
  print("[5/5] ポートフォリオ構築中...")
  # JP OCリターンをアラインメント済みデータから抽出
  jpOcCols = {f"jp_oc_{t}": t for t in JP_TICKERS}
  jpOcAligned = aligned[[c for c in jpOcCols if c in aligned.columns]].rename(columns=jpOcCols)
  jpOcAligned = jpOcAligned[(jpOcAligned.index >= backtestStart) & (jpOcAligned.index <= backtestEnd)]

  portfolio = constructPortfolio(signals, jpOcAligned, q=q)
  metrics = calcMetrics(portfolio["port_return"])

  # Step 6: PCA + JP モメンタム (Enhanced)
  print("[6/6] Enhanced シグナル生成中 (PCA + JP MOM)...")
  signalsEnh = generateSignalsEnhanced(aligned, lam=lam, k=k, window=window)
  signalsEnh = signalsEnh[(signalsEnh.index >= backtestStart) & (signalsEnh.index <= backtestEnd)]
  portfolioEnh = constructPortfolio(signalsEnh, jpOcAligned, q=q)
  metricsEnh = calcMetrics(portfolioEnh["port_return"])

  # 結果表示
  print()
  print("=" * 60)
  print(f"{'':20s} {'PCA SUB':>12s}  {'+ JP MOM':>12s}")
  print("=" * 60)
  print(f"  {'年率リターン (AR)':20s} {metrics['ar']:>11.2f}%  {metricsEnh['ar']:>11.2f}%")
  print(f"  {'年率リスク (RISK)':20s} {metrics['risk']:>11.2f}%  {metricsEnh['risk']:>11.2f}%")
  print(f"  {'R/R':20s} {metrics['rr']:>12.2f}  {metricsEnh['rr']:>12.2f}")
  print(f"  {'最大DD (MDD)':20s} {metrics['mdd']:>11.2f}%  {metricsEnh['mdd']:>11.2f}%")
  print(f"  {'勝率':20s} {metrics['hitRate']:>11.1f}%  {metricsEnh['hitRate']:>11.1f}%")
  print(f"  {'トータルリターン':20s} {metrics['totalReturn']:>11.2f}%  {metricsEnh['totalReturn']:>11.2f}%")
  print(f"  {'取引日数':20s} {len(portfolio):>12d}  {len(portfolioEnh):>12d}")
  print()
  print("--- 論文参考値 (Table 2) ---")
  print("  AR: 23.79% / RISK: 10.70% / R/R: 2.22 / MDD: -9.58%")

  return {
    "metrics": metrics,
    "metricsEnh": metricsEnh,
    "portfolio": portfolio,
    "portfolioEnh": portfolioEnh,
    "signals": signals,
    "signalsEnh": signalsEnh,
  }


if __name__ == "__main__":
  result = runBacktest()
