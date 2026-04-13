"""
日本株ギャップスキャナー

毎朝実行して、GD/GU候補銘柄の検出と判断材料を提供する。
寄り前に知れる情報のみを使用。
"""

import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# 監視ユニバース（流動性・知名度の高い大型株中心）
UNIVERSE = [
  "6758.T", "8306.T", "9984.T", "7203.T", "6501.T", "8035.T",
  "9101.T", "6098.T", "4063.T", "8411.T", "7974.T", "6902.T",
  "3382.T", "4568.T", "1605.T", "5020.T", "8604.T", "5401.T",
  "7201.T", "2413.T", "3659.T", "1570.T", "1357.T",
]

# 銘柄名マッピング（表示用）
SYMBOL_NAMES = {
  "6758.T": "ソニーG",
  "8306.T": "三菱UFJ",
  "9984.T": "ソフトバンクG",
  "7203.T": "トヨタ",
  "6501.T": "日立",
  "8035.T": "東京エレクトロン",
  "9101.T": "日本郵船",
  "6098.T": "リクルートHD",
  "4063.T": "信越化学",
  "8411.T": "みずほFG",
  "7974.T": "任天堂",
  "6902.T": "デンソー",
  "3382.T": "セブン&iHD",
  "4568.T": "第一三共",
  "1605.T": "INPEX",
  "5020.T": "ENEOS",
  "8604.T": "野村HD",
  "5401.T": "日本製鉄",
  "7201.T": "日産自動車",
  "2413.T": "エムスリー",
  "3659.T": "ネクソン",
  "1570.T": "日経レバETF",
  "1357.T": "日経ダブルイン",
}

JST = timezone(timedelta(hours=9))


def _fetchOhlcv(symbol: str, years: int = 1) -> pd.DataFrame | None:
  """yfinanceで日足OHLCVを取得。失敗時はNone"""
  try:
    from strategies.jp_stock.data import fetchOhlcv
    return fetchOhlcv(symbol, interval="1d", years=years)
  except Exception:
    return None


def _calcAtr(df: pd.DataFrame, period: int = 14) -> float:
  """ATR(14日)をパーセンテージで返す"""
  if len(df) < period + 1:
    return 0.0
  high = df["high"].values
  low = df["low"].values
  close = df["close"].values
  trs = []
  for i in range(1, len(df)):
    tr = max(
      high[i] - low[i],
      abs(high[i] - close[i - 1]),
      abs(low[i] - close[i - 1]),
    )
    trs.append(tr)
  trs = np.array(trs[-period:])
  atr = np.mean(trs)
  lastClose = close[-1]
  if lastClose <= 0:
    return 0.0
  return atr / lastClose * 100


def _calcMomentum5(df: pd.DataFrame) -> float:
  """直近5日の騰落率(%)"""
  if len(df) < 6:
    return 0.0
  closes = df["close"].values
  return (closes[-1] / closes[-6] - 1) * 100


def _calcVolTrend(df: pd.DataFrame) -> float:
  """直近5日出来高 / 直近20日平均出来高 の比率"""
  if len(df) < 21:
    return 1.0
  vols = df["volume"].values
  avg20 = np.mean(vols[-21:-1])
  avg5 = np.mean(vols[-5:])
  if avg20 <= 0:
    return 1.0
  return avg5 / avg20


def _calcHistFillRate(df: pd.DataFrame, gdThreshold: float = 2.0, lookback: int = 60) -> float:
  """
  過去lookback日のGDイベントのうち、当日中にギャップを埋めた比率を返す。
  GD = 始値が前日終値より gdThreshold% 以上下落。
  埋め = 当日高値が前日終値以上。
  """
  if len(df) < lookback + 1:
    return 0.0

  closes = df["close"].values
  opens = df["open"].values
  highs = df["high"].values

  gdCount = 0
  fillCount = 0
  start = max(1, len(df) - lookback)
  for i in range(start, len(df)):
    prevClose = closes[i - 1]
    if prevClose <= 0:
      continue
    gapPct = (opens[i] - prevClose) / prevClose * 100
    if gapPct <= -gdThreshold:
      gdCount += 1
      # 高値が前日終値以上 → ギャップフィル成功
      if highs[i] >= prevClose:
        fillCount += 1

  if gdCount == 0:
    return 0.0
  return fillCount / gdCount * 100


def calcEntryScore(symbol: str, df: pd.DataFrame = None) -> dict:
  """
  前日終値ベースのエントリースコアを計算する。

  返り値:
    atrPct: ATR(14日)のパーセンテージ
    mom5: 5日モメンタム(%)
    volTrend: 5日出来高 / 20日平均出来高
    histFillRate: 過去60日のギャップフィル率(%)
    lastClose: 前日終値
    recommendation: ENTRY / CAUTION / SKIP
    reason: 判定理由のリスト
  """
  if df is None:
    df = _fetchOhlcv(symbol, years=1)

  if df is None or len(df) < 30:
    return {
      "symbol": symbol,
      "atrPct": 0.0,
      "mom5": 0.0,
      "volTrend": 1.0,
      "histFillRate": 0.0,
      "lastClose": 0.0,
      "recommendation": "SKIP",
      "reason": ["データ取得失敗"],
    }

  atrPct = _calcAtr(df)
  mom5 = _calcMomentum5(df)
  volTrend = _calcVolTrend(df)
  histFillRate = _calcHistFillRate(df)
  lastClose = float(df["close"].iloc[-1])
  lastDate = df.index[-1].strftime("%m/%d") if hasattr(df.index[-1], "strftime") else ""

  # 推奨アクション判定
  # SKIP条件（最優先）
  skipReasons = []
  if atrPct < 1.5:
    skipReasons.append(f"ATR低({atrPct:.1f}%<1.5%)")
  if histFillRate < 15.0:
    skipReasons.append(f"フィル率低({histFillRate:.0f}%<15%)")

  # ENTRY条件
  entryOk = (
    atrPct >= 2.0
    and mom5 < 0
    and histFillRate >= 30.0
  )

  cautionReasons = []
  if atrPct < 2.0 and atrPct >= 1.5:
    cautionReasons.append(f"ATR弱({atrPct:.1f}%<2%)")
  if mom5 >= 0:
    cautionReasons.append(f"mom5={mom5:+.1f}%(上昇中)")
  if histFillRate < 30.0 and histFillRate >= 15.0:
    cautionReasons.append(f"フィル率{histFillRate:.0f}%<30%")

  if skipReasons:
    rec = "SKIP"
    reason = skipReasons
  elif entryOk:
    rec = "ENTRY"
    reason = [f"ATR={atrPct:.1f}%", f"mom5={mom5:+.1f}%", f"フィル率={histFillRate:.0f}%"]
  else:
    rec = "CAUTION"
    reason = cautionReasons if cautionReasons else ["条件一部未達"]

  # 総合スコア (0-100)
  # 各指標を0-25点に正規化して合算
  # ATR: 1.5以下=0, 5以上=25
  atrScore = min(25, max(0, (atrPct - 1.5) / (5.0 - 1.5) * 25))
  # mom5: +5以上=0, -5以下=25（下がっているほど良い）
  momScore = min(25, max(0, (5 - mom5) / 10 * 25))
  # volTrend: 0.5以下=0, 2.0以上=25
  volScore = min(25, max(0, (volTrend - 0.5) / (2.0 - 0.5) * 25))
  # histFillRate: 0%=0, 50%以上=25
  fillScore = min(25, max(0, histFillRate / 50 * 25))
  totalScore = round(atrScore + momScore + volScore + fillScore)

  return {
    "symbol": symbol,
    "atrPct": round(atrPct, 2),
    "mom5": round(mom5, 2),
    "volTrend": round(volTrend, 2),
    "histFillRate": round(histFillRate, 1),
    "lastClose": lastClose,
    "lastDate": lastDate,
    "recommendation": rec,
    "reason": reason,
    "score": totalScore,
  }


def checkFundamentals(symbol: str) -> list[dict]:
  """
  yfinanceのnewsから直近ニュースを取得して返す。
  ユーザーが手動判断するための材料として使う。

  返り値: [{"title": str, "url": str, "publishedAt": str}, ...]
  """
  try:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    news = ticker.news
    if not news:
      return []
    items = []
    for item in news[:5]:
      content = item.get("content", {})
      title = content.get("title", item.get("title", ""))
      url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content, dict) else ""
      if not url:
        url = item.get("link", "")
      publishedAt = ""
      pubDate = content.get("pubDate", "") if isinstance(content, dict) else ""
      if pubDate:
        publishedAt = pubDate[:10]
      items.append({"title": title, "url": url, "publishedAt": publishedAt})
    return items
  except Exception:
    return []


def scanGaps(symbols: list[str] = None, gdThreshold: float = 2.0) -> list[dict]:
  """
  各銘柄の前日終値をベースにGD候補一覧を返す。

  リアルタイム気配は取れないため、「各銘柄の前日終値から gdThreshold% 下落した水準」
  をGDエントリー想定価格として算出し、スコアとあわせてリストを返す。

  返り値: [
    {
      "symbol": str,
      "name": str,
      "lastClose": float,
      "gdEntryPrice": float,   # 前日終値 × (1 - gdThreshold/100)
      "atrPct": float,
      "mom5": float,
      "volTrend": float,
      "histFillRate": float,
      "recommendation": str,
      "reason": list[str],
    }
  ]
  """
  if symbols is None:
    symbols = UNIVERSE

  candidates = []
  for sym in symbols:
    try:
      df = _fetchOhlcv(sym, years=1)
      if df is None or len(df) < 30:
        continue
      score = calcEntryScore(sym, df)
      lastClose = score["lastClose"]
      if lastClose <= 0:
        continue
      gdEntryPrice = lastClose * (1 - gdThreshold / 100)
      candidates.append({
        "symbol": sym,
        "name": SYMBOL_NAMES.get(sym, sym),
        "lastClose": lastClose,
        "lastDate": score.get("lastDate", ""),
        "gdEntryPrice": round(gdEntryPrice, 1),
        "atrPct": score["atrPct"],
        "mom5": score["mom5"],
        "volTrend": score["volTrend"],
        "histFillRate": score["histFillRate"],
        "recommendation": score["recommendation"],
        "reason": score["reason"],
        "score": score["score"],
      })
    except Exception:
      continue

  # ATRスコア順（高いほど値幅が出やすい）でソート
  candidates.sort(key=lambda x: x["atrPct"], reverse=True)
  return candidates


def _fetchNikkei225Futures() -> dict:
  """
  日経225 (^N225) の前日終値と簡易トレンドを取得。
  先物リアルタイムは取れないため日経ETF(1570.T)で代替。
  """
  result = {"price": None, "change": None, "trend": "不明"}
  try:
    df = _fetchOhlcv("^N225", years=1)
    if df is None or len(df) < 2:
      return result
    lastClose = float(df["close"].iloc[-1])
    prevClose = float(df["close"].iloc[-2])
    chg = (lastClose / prevClose - 1) * 100 if prevClose > 0 else 0.0
    sma25 = float(df["close"].tail(25).mean())
    trend = "上昇" if lastClose > sma25 else "下落"
    result = {
      "price": round(lastClose, 0),
      "change": round(chg, 2),
      "trend": trend,
    }
  except Exception:
    pass
  return result


def _fetchUsdJpy() -> dict:
  """ドル円（USDJPY=X）の前日終値を取得"""
  result = {"rate": None, "change": None}
  try:
    import yfinance as yf
    df = yf.Ticker("USDJPY=X").history(period="5d", interval="1d")
    if df.empty or len(df) < 2:
      return result
    df.columns = [c.lower() for c in df.columns]
    lastRate = float(df["close"].iloc[-1])
    prevRate = float(df["close"].iloc[-2])
    chg = (lastRate / prevRate - 1) * 100 if prevRate > 0 else 0.0
    result = {"rate": round(lastRate, 2), "change": round(chg, 2)}
  except Exception:
    pass
  return result


def generateMorningReport(gdThreshold: float = 2.0) -> dict:
  """
  全ユニバースをスキャンして朝のレポートデータを生成する。

  返り値:
    {
      "generatedAt": str,
      "gdThreshold": float,
      "nikkei": {"price", "change", "trend"},
      "usdjpy": {"rate", "change"},
      "candidates": [...],  # scanGaps の返り値
      "entryCount": int,    # ENTRY推奨数
      "cautionCount": int,
      "skipCount": int,
    }
  """
  now = datetime.now(JST)
  nikkei = _fetchNikkei225Futures()
  usdjpy = _fetchUsdJpy()
  candidates = scanGaps(gdThreshold=gdThreshold)

  # ニュースチェックを加えて recommendation を更新
  # (ENTRY候補のみニュース取得でCPU節約)
  for c in candidates:
    if c["recommendation"] in ("ENTRY", "CAUTION"):
      news = checkFundamentals(c["symbol"])
      c["news"] = news
      # ニュースありならENTRY → CAUTION に格下げ
      if news and c["recommendation"] == "ENTRY":
        c["recommendation"] = "CAUTION"
        c["reason"].append(f"直近ニュース{len(news)}件")
    else:
      c["news"] = []

  entryCount = sum(1 for c in candidates if c["recommendation"] == "ENTRY")
  cautionCount = sum(1 for c in candidates if c["recommendation"] == "CAUTION")
  skipCount = sum(1 for c in candidates if c["recommendation"] == "SKIP")

  return {
    "generatedAt": now.isoformat(),
    "gdThreshold": gdThreshold,
    "nikkei": nikkei,
    "usdjpy": usdjpy,
    "candidates": candidates,
    "entryCount": entryCount,
    "cautionCount": cautionCount,
    "skipCount": skipCount,
  }


def formatReport(report: dict) -> str:
  """
  generateMorningReport の返り値をコンソール出力用テキストに整形する。
  """
  lines = []
  now = report.get("generatedAt", "")[:19].replace("T", " ")
  gdTh = report.get("gdThreshold", 2.0)
  lines.append(f"  生成: {now} (GD閾値: -{gdTh:.1f}%)")

  # マクロ概況
  nk = report.get("nikkei", {})
  if nk.get("price") is not None:
    sign = "+" if (nk.get("change") or 0) >= 0 else ""
    lines.append(
      f"  日経225: {nk['price']:,.0f} ({sign}{nk.get('change', 0):.2f}%) "
      f"[{nk.get('trend', '')}トレンド]"
    )

  fx = report.get("usdjpy", {})
  if fx.get("rate") is not None:
    sign = "+" if (fx.get("change") or 0) >= 0 else ""
    lines.append(f"  ドル円: {fx['rate']:.2f} ({sign}{fx.get('change', 0):.2f}%)")

  entryN = report.get("entryCount", 0)
  cautionN = report.get("cautionCount", 0)
  skipN = report.get("skipCount", 0)
  lines.append(f"  候補: ENTRY={entryN} / CAUTION={cautionN} / SKIP={skipN}")
  lines.append("")

  candidates = report.get("candidates", [])
  if not candidates:
    lines.append("  銘柄データなし")
    return "\n".join(lines)

  # ヘッダー
  lines.append(
    f"  {'銘柄':>10s}  {'名前':>10s}  {'前日終値':>9s}  {'GD想定価格':>10s}  "
    f"{'ATR%':>5s}  {'mom5':>6s}  {'volTrend':>8s}  {'フィル率':>6s}  {'推奨':>8s}"
  )
  lines.append("  " + "-" * 95)

  # 推奨順: ENTRY > CAUTION > SKIP
  order = {"ENTRY": 0, "CAUTION": 1, "SKIP": 2}
  sortedCandidates = sorted(candidates, key=lambda x: (order.get(x["recommendation"], 9), -x["atrPct"]))

  for c in sortedCandidates:
    rec = c["recommendation"]
    recLabel = {"ENTRY": "ENTRY", "CAUTION": "CAUTION", "SKIP": "SKIP"}.get(rec, rec)
    lines.append(
      f"  {c['symbol']:>10s}  {c['name']:>10s}  {c['lastClose']:>9,.1f}  "
      f"{c['gdEntryPrice']:>10,.1f}  {c['atrPct']:>5.1f}  {c['mom5']:>+6.1f}  "
      f"{c['volTrend']:>8.2f}  {c['histFillRate']:>6.1f}%  {recLabel:>8s}"
    )
    if c.get("reason"):
      lines.append(f"    理由: {' / '.join(c['reason'])}")
    news = c.get("news", [])
    if news:
      for n in news[:2]:
        title = n.get("title", "")[:60]
        lines.append(f"    NEWS: {title}")
    lines.append("")

  return "\n".join(lines)
