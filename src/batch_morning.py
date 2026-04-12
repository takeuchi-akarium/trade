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

import json
import traceback
import requests
from datetime import datetime, timedelta, timezone

from common.config_loader import load_config
from common.notifier import notify
from common.logger import log, cleanup


# ── BTC セクション ──────────────────────────────────

def buildBtcSection():
  """CoinGecko APIでBTC価格情報を取得してレポート文字列を返す"""
  try:
    resp = requests.get(
      "https://api.coingecko.com/api/v3/coins/bitcoin",
      params={
        "localization": "false",
        "tickers": "false",
        "community_data": "false",
        "developer_data": "false",
      },
      headers={"User-Agent": "Mozilla/5.0"},
      timeout=10,
    )
    resp.raise_for_status()
    md = resp.json().get("market_data", {})

    price = md.get("current_price", {}).get("usd", 0)
    chg = md.get("price_change_percentage_24h", 0)
    high = md.get("high_24h", {}).get("usd", 0)
    low = md.get("low_24h", {}).get("usd", 0)
    sign = "+" if chg >= 0 else ""

    lines = []
    lines.append(f"  現在値: ${price:,.0f} ({sign}{chg:.1f}%)")
    if high and low:
      lines.append(f"  24h高値: ${high:,.0f} / 安値: ${low:,.0f}")
    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildBtcSection error: {traceback.format_exc()}")
    return f"  取得失敗: {e}"


# ── マクロシグナル セクション ────────────────────────

def buildMacroSection(config):
  """マクロ指標を収集してレポート文字列を返す。latest_signal.json も更新する"""
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

    # ダッシュボード用に latest_signal.json を更新
    signalPath = ROOT / "data" / "signals" / "latest_signal.json"
    signalPath.parent.mkdir(parents=True, exist_ok=True)
    signalPath.write_text(
      json.dumps({
        "signal": signal,
        "total": total,
        "scores": result["scores"],
        "details": result["details"],
        "updated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
      }, indent=2, ensure_ascii=False),
      encoding="utf-8",
    )

    icon = {"BUY": "強気", "SELL": "弱気"}.get(signal, "中立")
    lines = [f"  判定: {icon} ({signal})  スコア: {total:+d}"]
    for k, v in result["details"].items():
      scoreStr = f"{result['scores'][k]:+d}" if k in result["scores"] else "N/A"
      lines.append(f"  {k}: {v} ({scoreStr})")
    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildMacroSection error: {traceback.format_exc()}")
    return f"  取得失敗: {e}"


# ── ファンダスコア セクション ────────────────────────

def buildFundaSection():
  """BTCトレンド予測ファンダスコアを算出してレポート文字列を返す"""
  try:
    from signals.collectors.macro_collector import (
      get_gold_history, get_tnx_history, get_fng_history,
    )
    from signals.scorer import calcFundaScore

    goldHist = get_gold_history(days=60)
    tnxHist = get_tnx_history(days=30)
    fngHist = get_fng_history(days=40)
    score = calcFundaScore(goldHist, tnxHist, fngHist)

    if score > 0.5:
      label = "強気 (Boost対象)"
    elif score > 0.3:
      label = "やや強気"
    elif score < -0.3:
      label = "やや弱気 (Early Transition対象)"
    elif score < -0.5:
      label = "弱気 (Early Transition対象)"
    else:
      label = "中立"

    lines = [f"  スコア: {score:+.2f} → {label}"]

    if goldHist:
      goldMom = (goldHist[-1] / goldHist[0] - 1) * 100 if goldHist[0] > 0 else 0
      lines.append(f"  Gold: ${goldHist[-1]:,.0f} ({len(goldHist)}d mom: {goldMom:+.1f}%)")
    if tnxHist:
      tnxChg = tnxHist[-1] - tnxHist[0] if len(tnxHist) > 1 else 0
      lines.append(f"  10Y: {tnxHist[-1]:.2f}% ({len(tnxHist)}d chg: {tnxChg:+.2f})")
    if fngHist:
      lines.append(f"  FnG: {fngHist[-1]} (7d avg: {sum(fngHist[-7:])/min(7,len(fngHist)):.0f})")

    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildFundaSection error: {traceback.format_exc()}")
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
      lines.append(f"  [{icon}{abs(score)}] {item['title']} ({item['source']})\n    {item['url']}")
    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildRssSection error: {traceback.format_exc()}")
    return f"  取得失敗: {e}"


# ── TDnet 適時開示 セクション ────────────────────────

def buildTdnetSection(config):
  """TDnet適時開示を取得してレポート文字列を返す"""
  try:
    from signals.collectors.tdnet_collector import fetch_disclosures
    from signals.alert_dispatcher import (
      score_text, TDNET_BUY_KEYWORDS, TDNET_SELL_KEYWORDS, classify_tob,
    )

    tdnetCfg = config.get("tdnet", {})
    if not tdnetCfg.get("enabled", True):
      return "  無効"

    categories = tdnetCfg.get("categories", ["決算", "配当", "業績修正", "買付", "交換", "買収"])
    threshold = tdnetCfg.get("score_threshold", 40)
    items = fetch_disclosures(categories)

    if not items:
      return "  開示なし"

    # スコアリング + フィルタ
    scored = []
    for item in items:
      score, matched = score_text(item["title"], TDNET_BUY_KEYWORDS, TDNET_SELL_KEYWORDS)
      # TOB/MBO判定 — 該当すればスコア・キーワードを上書き
      tob_role, tob_score, tob_kws = classify_tob(item["title"], item.get("name", ""))
      if tob_role is not None:
        score = tob_score
        matched = tob_kws
      if abs(score) < threshold:
        continue
      scored.append((item, score, matched, tob_role))

    if not scored:
      return "  該当なし"

    # スコア絶対値でソート、上位5件
    scored.sort(key=lambda x: abs(x[1]), reverse=True)
    lines = []
    for item, score, matched, tob_role in scored[:5]:
      icon = "+" if score > 0 else "-"
      kwStr = "/".join(matched) if matched else ""
      role_tag = ""
      if tob_role == "target":
        role_tag = " 📌被買付"
      elif tob_role == "acquirer":
        role_tag = " 📌買付側"
      lines.append(f"  [{icon}{abs(score)}] {item['code']} {item['name']} {kwStr}{role_tag}\n    {item['url']}")
    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildTdnetSection error: {traceback.format_exc()}")
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

    # yfinance の end は排他的（その日を含まない）ため、翌日を指定して当日データを含める
    # GitHub Actions は 22:00 UTC (= JST 07:00) に実行されるので JST 基準で計算
    jst = timezone(timedelta(hours=9))
    tomorrow = (datetime.now(jst) + timedelta(days=1)).strftime("%Y-%m-%d")
    usPrices, jpPrices = fetchAllPrices(start="2009-01-01", end=tomorrow)

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
    recordPosition(positions, todaySignal["date"], positionFile, todaySignal.get("confidence"))

    return report
  except Exception as e:
    return f"[leadlag] エラー: {e}"


# ── 日本小型株モメンタム セクション ─────────────────────

def buildJpMomentumSection():
  """日本小型株モメンタムランキングTOP10を生成"""
  try:
    import numpy as np
    from strategies.jp_stock.data import getSmallCapUniverse, fetchOhlcv

    universe = getSmallCapUniverse()

    # 日経225で市場トレンド判定
    nk = fetchOhlcv("^N225", interval="1d", years=1)
    nkPrice = nk["close"].iloc[-1]
    nkSma200 = nk["close"].tail(200).mean()
    marketOk = nkPrice > nkSma200
    trendStr = "上昇" if marketOk else "下落"

    lines = [f"  日経225: {nkPrice:,.0f} (SMA200: {nkSma200:,.0f}) -> {trendStr}トレンド"]

    if not marketOk:
      lines.append("  ** 市場下落中: 新規エントリー非推奨（現金待機）**")
      return "\n".join(lines)

    # 全銘柄のモメンタムを計算
    momentum = []
    checked = 0
    for stock in universe:
      sym = stock["symbol"]
      try:
        df = fetchOhlcv(sym, interval="1d", years=1)
        if len(df) < 80:
          continue
        checked += 1

        price = df["close"].iloc[-1]
        if price < 200:
          continue
        avgVol = df["volume"].tail(20).mean()
        if avgVol < 30000:
          continue

        ret60 = (price / df["close"].iloc[-60] - 1) * 100 if len(df) >= 60 else 0
        ret20 = (price / df["close"].iloc[-20] - 1) * 100 if len(df) >= 20 else 0

        momentum.append({
          "symbol": sym,
          "name": stock.get("name", ""),
          "price": price,
          "ret60": ret60,
          "ret20": ret20,
          "avgVol": avgVol,
        })
      except Exception:
        continue

      # 上位を決めるのに十分なデータがあれば途中で切り上げ
      if checked >= 500 and len(momentum) >= 50:
        break

    if not momentum:
      lines.append("  データ取得失敗")
      return "\n".join(lines)

    # 60日リターン上位10銘柄
    momentum.sort(key=lambda x: x["ret60"], reverse=True)
    top10 = momentum[:10]

    lines.append(f"  (検査: {checked}銘柄 / 通過: {len(momentum)}銘柄)")
    lines.append("")
    lines.append("  順位  銘柄      株価      60日     20日    出来高")
    lines.append("  " + "-" * 55)

    for i, m in enumerate(top10):
      lines.append(
        f"  {i+1:>3d}.  {m['symbol']:>8s}  {m['price']:>7,.0f}  "
        f"{m['ret60']:>+6.1f}%  {m['ret20']:>+6.1f}%  {m['avgVol']:>9,.0f}"
      )

    # 現在保有との差分（前回のTOP10と比較）
    top10Path = ROOT / "data" / "jp_stock" / "prev_top10.json"
    prevSymbols = set()
    if top10Path.exists():
      prev = json.loads(top10Path.read_text(encoding="utf-8"))
      prevSymbols = set(prev.get("symbols", []))

    currentSymbols = set(m["symbol"] for m in top10)
    newIn = currentSymbols - prevSymbols
    droppedOut = prevSymbols - currentSymbols

    if newIn or droppedOut:
      lines.append("")
      if newIn:
        lines.append(f"  新規: {', '.join(sorted(newIn))}")
      if droppedOut:
        lines.append(f"  脱落: {', '.join(sorted(droppedOut))}")

    # 保存
    top10Path.parent.mkdir(parents=True, exist_ok=True)
    top10Path.write_text(
      json.dumps({
        "symbols": sorted(currentSymbols),
        "date": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"),
        "top10": [{k: v for k, v in m.items() if k != "avgVol"} for m in top10],
      }, ensure_ascii=False, indent=2),
      encoding="utf-8",
    )

    return "\n".join(lines)
  except Exception as e:
    log("batch_morning", f"buildJpMomentumSection error: {traceback.format_exc()}")
    return f"  取得失敗: {e}"


# ── デュアルモメンタム セクション ──────────────────────

def buildDualMomentumSection(config):
  """デュアルモメンタム (GEM) のシグナルを生成してレポート文字列を返す"""
  try:
    from dual_momentum.fetch_data import fetchPrices
    from dual_momentum.signal_generator import generateTodaySignal
    from dual_momentum.report import buildReport

    prices = fetchPrices()
    todaySignal = generateTodaySignal(prices)

    # 前月シグナルとの比較
    prevSignal = None
    prevPath = ROOT / "data" / "dual_momentum" / "prev_signal.json"
    if prevPath.exists():
      prev = json.loads(prevPath.read_text(encoding="utf-8"))
      prevSignal = prev.get("signal")

    report = buildReport(todaySignal, prevSignal)

    # 今月のシグナルを保存
    if todaySignal:
      prevPath.parent.mkdir(parents=True, exist_ok=True)
      prevPath.write_text(
        json.dumps({"signal": todaySignal["signal"], "date": todaySignal["date"]},
                   ensure_ascii=False), encoding="utf-8")

    return report
  except Exception as e:
    log("batch_morning", f"buildDualMomentumSection error: {traceback.format_exc()}")
    return f"  取得失敗: {e}"


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

  # 2. デュアルモメンタム
  log("batch_morning", "デュアルモメンタム...")
  sections.append(f"■ デュアルモメンタム (GEM)\n{buildDualMomentumSection(config)}")

  # 3. BTC
  log("batch_morning", "BTC...")
  sections.append(f"■ BTC（前日）\n{buildBtcSection()}")

  # 4. マクロシグナル
  log("batch_morning", "マクロ...")
  sections.append(f"■ マクロシグナル\n{buildMacroSection(config)}")

  # 5. ファンダスコア（BTCトレンド予測）
  log("batch_morning", "ファンダスコア...")
  sections.append(f"■ BTCファンダスコア\n{buildFundaSection()}")

  # 6. ニュース
  log("batch_morning", "RSS...")
  sections.append(f"■ 注目ニュース\n{buildRssSection(config)}")

  # 7. TDnet
  log("batch_morning", "TDnet...")
  sections.append(f"■ 適時開示\n{buildTdnetSection(config)}")

  # 8. 日本小型株モメンタムTOP10
  log("batch_morning", "JP momentum...")
  sections.append(f"■ 日本小型株 モメンタムTOP10\n{buildJpMomentumSection()}")

  # 統合レポート送信
  report = "\n\n".join(sections)
  print(report)
  notify(report, config)

  log("batch_morning", "完了")
  cleanup()


if __name__ == "__main__":
  main()
