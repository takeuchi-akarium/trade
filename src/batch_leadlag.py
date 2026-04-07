"""
日米リードラグ戦略 — 毎朝バッチ

毎朝 7:00 JST (米国市場クローズ後、東証寄付き前) に実行。
1. 米国前日リターン取得
2. シグナル計算
3. AIコメント生成
4. Discord/LINE通知
5. ポジション履歴記録
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# パス設定
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

import pandas as pd
from datetime import datetime, timedelta, timezone

from leadlag.constants import US_TICKERS, JP_TICKERS
from leadlag.fetch_data import fetchAllPrices, calcCcReturns, calcOcReturns
from leadlag.calendar_align import alignReturns
from leadlag.signal_generator import generateTodaySignal
from leadlag.portfolio import selectPositions, recordPosition
from leadlag.metrics import calcRunningMetrics
from leadlag.report import buildReport, generateAiComment
from common.config_loader import load_config
from common.notifier import notify
from common.logger import log

DATA_DIR = ROOT / "data" / "leadlag"
POSITION_FILE = DATA_DIR / "position_history.json"


def main():
  log("batch_leadlag", "開始")
  config = load_config()

  try:
    # Step 1: データ取得 (増分更新)
    log("batch_leadlag", "データ取得中...")
    # yfinance の end は排他的なので翌日を指定して当日データを含める
    jst = timezone(timedelta(hours=9))
    tomorrow = (datetime.now(jst) + timedelta(days=1)).strftime("%Y-%m-%d")
    usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end=tomorrow)

    # Step 2: リターン計算 + アラインメント
    usRetCc = calcCcReturns(usPrices, US_TICKERS)
    jpRetCc = calcCcReturns(jpPrices, JP_TICKERS)
    jpRetOc = calcOcReturns(jpPrices, JP_TICKERS)
    aligned = alignReturns(usRetCc, jpRetCc, jpRetOc)

    # Step 3: 本日シグナル生成
    log("batch_leadlag", "シグナル計算中...")
    todaySignal = generateTodaySignal(aligned)
    positions = selectPositions(todaySignal)

    # Step 4: 実績計算 (過去ポジションのリターン)
    # 簡易的に前日分のみ計算
    runningMetrics = {"lastDay": 0, "mtd": 0, "ytd": 0}
    try:
      from leadlag.signal_generator import generateSignals
      from leadlag.portfolio import constructPortfolio

      leadlagConfig = config.get("leadlag", {})
      backtestStart = leadlagConfig.get("backtest_start", "2015-01-01")
      signals = generateSignals(aligned)
      signals = signals[signals.index >= backtestStart]

      jpOcCols = {f"jp_oc_{t}": t for t in JP_TICKERS}
      jpOcAligned = aligned[[c for c in jpOcCols if c in aligned.columns]].rename(columns=jpOcCols)
      portfolio = constructPortfolio(signals, jpOcAligned)

      if len(portfolio) > 0:
        runningMetrics = calcRunningMetrics(portfolio["port_return"])
    except Exception as e:
      log("batch_leadlag", f"実績計算スキップ: {e}")

    # Step 5: AIコメント生成
    log("batch_leadlag", "AIコメント生成中...")
    aiComment = generateAiComment(todaySignal, positions)

    # Step 6: レポート生成 + 通知
    report = buildReport(positions, todaySignal, runningMetrics, aiComment)
    print(report)
    notify(report, config)

    # Step 7: ポジション履歴記録
    recordPosition(positions, todaySignal["date"], POSITION_FILE)

    log("batch_leadlag", "完了")

  except Exception as e:
    errMsg = f"[leadlag] エラー: {e}"
    log("batch_leadlag", errMsg)
    print(errMsg)
    # エラー時も通知
    try:
      notify(errMsg, config)
    except Exception:
      pass


if __name__ == "__main__":
  main()
