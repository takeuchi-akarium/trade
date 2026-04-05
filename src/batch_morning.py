"""
統合朝バッチ: 全情報を1つのレポートにまとめて朝7時に送信

GitHub Actions で毎朝 7:00 JST に実行。
各バッチ (leadlag, BTC, macro, RSS, TDnet) の情報を1通にまとめる。
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

import requests
from datetime import datetime, timedelta, timezone

from common.config_loader import load_config
from common.notifier import notify
from common.logger import log, cleanup


# ── BTC セクション ──────────────────────────────────

def buildBtcSection():
  """Binance APIで前日のBTC OHLC を取得してレポート文字列を返す"""
  try:
    # 前日の日足を取得
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    resp = requests.get(
      "https://api.binance.com/api/v3/klines",
      params={
        "symbol": "BTCUSDT",
        "interval": "1d",
        "startTime": int(yesterday.timestamp() * 1000),
        "limit": 1,
      },
      timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
      return "  データなし"

    k = data[0]
    o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
    chg = (c - o) / o * 100
    sign = "+" if chg >= 0 else ""

    lines = []
    lines.append(f"  始値: ${o:,.0f} -> 終値: ${c:,.0f} ({sign}{chg:.1f}%)")
    lines.append(f"  高値: ${h:,.0f} / 安値: ${l:,.0f}")
    return "\n".join(lines)
  except Exception as e:
    return f"  取得失敗: {e}"


# ── マクロシグナル セクション ────────────────────────

def buildMacroSection(config):
  """マクロ指標を収集してレポート文字列を返す"""
  try:
    from signals.aggregator import collect_and_score, to_signal
    sigCfg = config.get("signal", {})
    result = collect_and_score(sigCfg.get("weights"))
    total = result["total"]
    signal = to_signal(
      total,
      buy_threshold=sigCfg.get("buy_threshold", 30),
      sell_threshold=sigCfg.get("sell_threshold", -30),
    )

    icon = {"BUY": "強気", "SELL": "弱気"}.get(signal, "中立")
    lines = [f"  判定: {icon} ({signal})  スコア: {total:+d}"]
    for k, v in result["details"].items():
      scoreStr = f"{result['scores'][k]:+d}" if k in result["scores"] else "N/A"
      lines.append(f"  {k}: {v} ({scoreStr})")
    return "\n".join(lines)
  except Exception as e:
    return f"  取得失敗: {e}"


# ── RSS ニュース セクション ──────────────────────────

def buildRssSection(config):
  """RSSフィードから注目ニュースを取得してレポート文字列を返す"""
  try:
    from signals.collectors.rss_collector import fetch_news, DEFAULT_FEEDS
    from signals.alert_dispatcher import (
      score_text, NEWS_BULL_KEYWORDS, NEWS_BEAR_KEYWORDS,
      _is_overseas_source, _is_japan_relevant,
    )

    rssCfg = config.get("rss", {})
    if not rssCfg.get("enabled", True):
      return "  無効"

    feeds = rssCfg.get("feeds", DEFAULT_FEEDS)
    threshold = rssCfg.get("score_threshold", 30)
    items = fetch_news(feeds)

    if not items:
      return "  ニュースなし"

    # スコアリング + フィルタ
    scored = []
    for item in items:
      score, matched = score_text(item["title"], NEWS_BULL_KEYWORDS, NEWS_BEAR_KEYWORDS)
      if abs(score) < threshold:
        continue
      if _is_overseas_source(item.get("source", "")) and not _is_japan_relevant(item["title"], score):
        continue
      scored.append((item, score, matched))

    if not scored:
      return "  該当なし"

    # スコア絶対値でソート、上位5件
    scored.sort(key=lambda x: abs(x[1]), reverse=True)
    lines = []
    for item, score, matched in scored[:5]:
      icon = "+" if score > 0 else "-"
      lines.append(f"  [{icon}{abs(score)}] {item['title']} ({item['source']})")
    return "\n".join(lines)
  except Exception as e:
    return f"  取得失敗: {e}"


# ── TDnet 適時開示 セクション ────────────────────────

def buildTdnetSection(config):
  """TDnet適時開示を取得してレポート文字列を返す"""
  try:
    from signals.collectors.tdnet_collector import fetch_disclosures
    from signals.alert_dispatcher import (
      score_text, TDNET_BUY_KEYWORDS, TDNET_SELL_KEYWORDS,
    )

    tdnetCfg = config.get("tdnet", {})
    if not tdnetCfg.get("enabled", True):
      return "  無効"

    categories = tdnetCfg.get("categories", ["決算", "配当", "業績修正"])
    threshold = tdnetCfg.get("score_threshold", 40)
    items = fetch_disclosures(categories)

    if not items:
      return "  開示なし"

    # スコアリング + フィルタ
    scored = []
    for item in items:
      score, matched = score_text(item["title"], TDNET_BUY_KEYWORDS, TDNET_SELL_KEYWORDS)
      if abs(score) < threshold:
        continue
      scored.append((item, score, matched))

    if not scored:
      return "  該当なし"

    # スコア絶対値でソート、上位5件
    scored.sort(key=lambda x: abs(x[1]), reverse=True)
    lines = []
    for item, score, matched in scored[:5]:
      icon = "+" if score > 0 else "-"
      kwStr = "/".join(matched) if matched else ""
      lines.append(f"  [{icon}{abs(score)}] {item['code']} {item['name']} {kwStr}")
    return "\n".join(lines)
  except Exception as e:
    return f"  取得失敗: {e}"


# ── Leadlag セクション ───────────────────────────────

def buildLeadlagSection(config):
  """日米リードラグシグナルを生成してレポート文字列を返す"""
  try:
    import pandas as pd
    from leadlag.constants import US_TICKERS, JP_TICKERS
    from leadlag.fetch_data import fetchAllPrices, calcCcReturns, calcOcReturns
    from leadlag.calendar_align import alignReturns
    from leadlag.signal_generator import generateTodaySignal
    from leadlag.portfolio import selectPositions, recordPosition
    from leadlag.metrics import calcRunningMetrics
    from leadlag.report import buildReport, generateAiComment

    today = datetime.now().strftime("%Y-%m-%d")
    usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end=today)

    usRetCc = calcCcReturns(usPrices, US_TICKERS)
    jpRetCc = calcCcReturns(jpPrices, JP_TICKERS)
    jpRetOc = calcOcReturns(jpPrices, JP_TICKERS)
    aligned = alignReturns(usRetCc, jpRetCc, jpRetOc)

    todaySignal = generateTodaySignal(aligned)
    positions = selectPositions(todaySignal)

    # 実績計算
    runningMetrics = {"lastDay": 0, "mtd": 0, "ytd": 0}
    try:
      from leadlag.signal_generator import generateSignals
      from leadlag.portfolio import constructPortfolio

      leadlagCfg = config.get("leadlag", {})
      backtestStart = leadlagCfg.get("backtest_start", "2015-01-01")
      signals = generateSignals(aligned)
      signals = signals[signals.index >= backtestStart]

      jpOcCols = {f"jp_oc_{t}": t for t in JP_TICKERS}
      jpOcAligned = aligned[[c for c in jpOcCols if c in aligned.columns]].rename(columns=jpOcCols)
      portfolio = constructPortfolio(signals, jpOcAligned)
      if len(portfolio) > 0:
        runningMetrics = calcRunningMetrics(portfolio["port_return"])
    except Exception as e:
      log("batch_morning", f"実績計算スキップ: {e}")

    # AIコメント
    aiComment = None
    leadlagCfg = config.get("leadlag", {})
    if leadlagCfg.get("ai_comment", True):
      aiComment = generateAiComment(todaySignal, positions)

    report = buildReport(positions, todaySignal, runningMetrics, aiComment)

    # ポジション履歴記録
    dataDir = ROOT / "data" / "leadlag"
    positionFile = dataDir / "position_history.json"
    recordPosition(positions, todaySignal["date"], positionFile)

    return report
  except Exception as e:
    return f"[leadlag] エラー: {e}"


# ── メイン ───────────────────────────────────────────

def main():
  log("batch_morning", "統合朝バッチ開始")
  config = load_config()

  jst = timezone(timedelta(hours=9))
  now = datetime.now(jst)
  weekdays = ["月", "火", "水", "木", "金", "土", "日"]
  dateStr = f"{now.strftime('%Y-%m-%d')}({weekdays[now.weekday()]})"

  sections = []

  # 1. Leadlag (メインレポート)
  log("batch_morning", "leadlag...")
  leadlagReport = buildLeadlagSection(config)
  sections.append(leadlagReport)

  # 2. BTC
  log("batch_morning", "BTC...")
  sections.append(f"■ BTC（前日）\n{buildBtcSection()}")

  # 3. マクロシグナル
  log("batch_morning", "マクロ...")
  sections.append(f"■ マクロシグナル\n{buildMacroSection(config)}")

  # 4. ニュース
  log("batch_morning", "RSS...")
  sections.append(f"■ 注目ニュース\n{buildRssSection(config)}")

  # 5. TDnet
  log("batch_morning", "TDnet...")
  sections.append(f"■ 適時開示\n{buildTdnetSection(config)}")

  # 統合レポート送信
  report = "\n\n".join(sections)
  print(report)
  notify(report, config)

  log("batch_morning", "完了")
  cleanup()


if __name__ == "__main__":
  main()
