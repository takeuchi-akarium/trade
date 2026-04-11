"""
日本小型株スクリーニング

JPX上場銘柄一覧から小型株ユニバースを自動構築し、
出来高・株価フィルター + 市場トレンドフィルターを通してシグナルを検出する。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from strategies.jp_stock.data import fetchOhlcv, getSmallCapUniverse


# 値幅制限テーブル（前日終値 → 制限値幅）
PRICE_LIMIT_TABLE = [
  (100, 30), (200, 50), (500, 80), (700, 100),
  (1000, 150), (1500, 300), (2000, 400), (3000, 500),
  (5000, 700), (7000, 1000), (10000, 1500), (15000, 3000),
  (20000, 4000), (30000, 5000), (50000, 7000), (70000, 10000),
  (100000, 15000),
]


def getPriceLimit(prevClose: float) -> float:
  """前日終値から値幅制限を返す"""
  for threshold, limit in PRICE_LIMIT_TABLE:
    if prevClose < threshold:
      return limit
  return 30000


# ── 市場トレンドフィルター ──

def checkMarketTrend(minDays: int = 60) -> dict:
  """
  日経225 (^N225) で市場全体のトレンドを判定。

  Returns: {"trend": "up"|"down"|"neutral", "sma50": float, "sma200": float, "price": float}
  """
  try:
    df = fetchOhlcv("^N225", interval="1d", years=1)  # Nikkei 225
    if len(df) < 200:
      return {"trend": "neutral", "sma50": 0, "sma200": 0, "price": 0}

    price = df["close"].iloc[-1]
    sma50 = df["close"].tail(50).mean()
    sma200 = df["close"].tail(200).mean()

    if price > sma50 and sma50 > sma200:
      trend = "up"
    elif price < sma50 and sma50 < sma200:
      trend = "down"
    else:
      trend = "neutral"

    return {"trend": trend, "sma50": sma50, "sma200": sma200, "price": price}
  except Exception:
    return {"trend": "neutral", "sma50": 0, "sma200": 0, "price": 0}


# ── 個別株フィルター ──

def calcStockScore(df: pd.DataFrame) -> dict:
  """
  銘柄の「質」スコアを計算。

  Returns: {"rsi": float, "momentum20": float, "momentum60": float,
            "volTrend": float, "atr": float, "score": float}
  """
  close = df["close"]
  volume = df["volume"]

  # RSI(14)
  delta = close.diff()
  gain = delta.where(delta > 0, 0).rolling(14).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
  rs = gain / loss.replace(0, np.nan)
  rsi = 100 - (100 / (1 + rs))
  rsiVal = rsi.iloc[-1] if not rsi.empty else 50

  # モメンタム（20日、60日リターン）
  mom20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0
  mom60 = (close.iloc[-1] / close.iloc[-60] - 1) * 100 if len(close) >= 60 else 0

  # 出来高トレンド（5日平均 / 20日平均）
  vol5 = volume.tail(5).mean()
  vol20 = volume.tail(20).mean()
  volTrend = vol5 / vol20 if vol20 > 0 else 1.0

  # ATR(14) / 価格 → ボラティリティ
  high = df["high"]
  low = df["low"]
  prevClose = close.shift(1)
  tr = pd.concat([
    high - low,
    (high - prevClose).abs(),
    (low - prevClose).abs(),
  ], axis=1).max(axis=1)
  atr = tr.rolling(14).mean().iloc[-1]
  atrPct = atr / close.iloc[-1] * 100

  # 総合スコア（高いほど「動きそう」な銘柄）
  # モメンタム正 + 出来高増加 + 適度なボラ → 高スコア
  score = 0
  if 40 <= rsiVal <= 70:
    score += 20  # RSIが過熱でも売られすぎでもない
  if mom20 > 0:
    score += min(mom20, 30)  # 20日モメンタム正
  if volTrend > 1.2:
    score += 15  # 出来高増加傾向
  if 2 <= atrPct <= 6:
    score += 10  # 適度なボラティリティ

  return {
    "rsi": rsiVal,
    "momentum20": mom20,
    "momentum60": mom60,
    "volTrend": volTrend,
    "atrPct": atrPct,
    "score": score,
  }


# ── メインスクリーニング ──

def screenStocks(symbols: list[str] = None, minPrice: float = 200,
                 minAvgVolume: int = 30000, maxStocks: int = 100,
                 useJpxList: bool = True, years: int = 1,
                 verbose: bool = True) -> list[dict]:
  """
  銘柄スクリーニング

  1. JPXリストから小型株ユニバース取得（or 手動リスト）
  2. 株価・出来高フィルター
  3. 異常値除外
  4. 銘柄スコアでランキング

  Returns: [{"symbol": str, "data": DataFrame, "avgVolume": float, "lastPrice": float, "score": dict}, ...]
  """
  # 銘柄リスト取得
  if symbols is None and useJpxList:
    universe = getSmallCapUniverse()
    symbols = [s["symbol"] for s in universe]
    if verbose:
      print(f"  JPX universe: {len(symbols)} stocks")
    # 全銘柄は多すぎるのでランダムサンプル（本番は全件スキャン）
    if len(symbols) > maxStocks:
      import random
      random.seed(42)
      symbols = random.sample(symbols, maxStocks)
      if verbose:
        print(f"  Sampled: {len(symbols)} stocks")
  elif symbols is None:
    symbols = [
      "6526.T", "4431.T", "3482.T", "7033.T", "6564.T",
      "4053.T", "4485.T", "4165.T", "7806.T", "4440.T",
    ]

  results = []
  skipped = 0
  for idx, sym in enumerate(symbols):
    try:
      df = fetchOhlcv(sym, interval="1d", years=years)
      if len(df) < 60:
        skipped += 1
        continue

      lastPrice = df["close"].iloc[-1]
      if lastPrice < minPrice:
        skipped += 1
        continue

      avgVol20 = df["volume"].tail(20).mean()
      if avgVol20 < minAvgVolume:
        skipped += 1
        continue

      # 異常出来高チェック
      avgVol5 = df["volume"].tail(5).mean()
      if avgVol5 > avgVol20 * 10:
        skipped += 1
        continue

      score = calcStockScore(df)

      results.append({
        "symbol": sym,
        "data": df,
        "avgVolume": avgVol20,
        "lastPrice": lastPrice,
        "score": score,
      })

      if verbose and (idx + 1) % 20 == 0:
        print(f"  ... {idx + 1}/{len(symbols)} processed ({len(results)} passed)")

    except Exception:
      skipped += 1

  # スコア順にソート
  results.sort(key=lambda x: x["score"]["score"], reverse=True)

  if verbose:
    print(f"  -> {len(results)} passed, {skipped} skipped")

  return results


def scanVolumeBreakout(stocks: list[dict],
                       volMultiple: float = 2.5,
                       highPeriod: int = 20,
                       marketTrend: dict = None) -> list[dict]:
  """
  出来高急増ブレイクアウト シグナルスキャン

  条件:
  1. 当日出来高 >= 20日平均 x volMultiple
  2. 当日終値 >= highPeriod日の終値最高値
  3. 終値 > 5日SMA かつ 終値 > 25日SMA
  4. (市場トレンドが"down"の場合はスキップ)
  """
  # 市場トレンドフィルター
  if marketTrend and marketTrend.get("trend") == "down":
    return []  # 下落相場ではブレイクアウト戦略は休止

  signals = []
  for stock in stocks:
    df = stock["data"]
    if len(df) < max(highPeriod, 25) + 1:
      continue

    last = df.iloc[-1]
    price = last["close"]
    volume = last["volume"]

    avgVol20 = df["volume"].iloc[-21:-1].mean()
    highMax = df["close"].iloc[-highPeriod - 1:-1].max()
    sma5 = df["close"].tail(6).iloc[:-1].mean()
    sma25 = df["close"].tail(26).iloc[:-1].mean()

    volOk = volume >= avgVol20 * volMultiple
    highOk = price >= highMax
    trendOk = price > sma5 and price > sma25

    if volOk and highOk and trendOk:
      signals.append({
        "symbol": stock["symbol"],
        "price": price,
        "volume": volume,
        "volRatio": volume / avgVol20,
        "score": stock.get("score", {}).get("score", 0),
        "reason": f"vol x{volume / avgVol20:.1f}, {highPeriod}d high break",
      })

  # スコア順
  signals.sort(key=lambda x: x["score"], reverse=True)
  return signals


def scanBBSqueeze(stocks: list[dict],
                  bbPeriod: int = 20, bbStd: float = 2.0,
                  squeezePeriod: int = 60, squeezeThreshold: float = 1.2,
                  volMultiple: float = 1.5,
                  marketTrend: dict = None) -> list[dict]:
  """
  BBスクイーズブレイク シグナルスキャン

  条件:
  1. 直近5日のBB幅 <= 過去60日最小幅 x squeezeThreshold
  2. 終値 > アッパーバンド（+2sigma）
  3. ブレイク日の出来高 >= 10日平均 x volMultiple
  """
  # 下落相場でもスクイーズ→ブレイクはワークするが、条件を厳しくする
  if marketTrend and marketTrend.get("trend") == "down":
    volMultiple *= 1.5  # 出来高条件を厳しく
    squeezeThreshold *= 0.9  # スクイーズ条件を厳しく

  signals = []
  for stock in stocks:
    df = stock["data"]
    if len(df) < squeezePeriod + bbPeriod:
      continue

    close = df["close"]
    sma = close.rolling(bbPeriod).mean()
    std = close.rolling(bbPeriod).std()
    upper = sma + bbStd * std
    bandwidth = (2 * bbStd * std) / sma

    recentBW = bandwidth.tail(5).mean()
    minBW = bandwidth.tail(squeezePeriod).min()

    squeezed = recentBW <= minBW * squeezeThreshold

    lastPrice = close.iloc[-1]
    lastUpper = upper.iloc[-1]
    breakout = lastPrice > lastUpper

    avgVol10 = df["volume"].tail(11).iloc[:-1].mean()
    lastVol = df["volume"].iloc[-1]
    volOk = lastVol >= avgVol10 * volMultiple

    if squeezed and breakout and volOk:
      signals.append({
        "symbol": stock["symbol"],
        "price": lastPrice,
        "upperBand": lastUpper,
        "bandwidth": recentBW,
        "minBandwidth": minBW,
        "score": stock.get("score", {}).get("score", 0),
        "reason": f"squeeze break, BW={recentBW:.4f} (min={minBW:.4f})",
      })

  signals.sort(key=lambda x: x["score"], reverse=True)
  return signals


def runScreener(symbols: list[str] = None, useJpxList: bool = False, maxStocks: int = 50):
  """全スクリーニングを実行して結果を表示"""
  print("=== Japanese Small-Cap Screener ===\n")

  # 市場トレンド確認
  print("[0] Market trend check...")
  mkt = checkMarketTrend()
  trendEmoji = {"up": "UP", "down": "DOWN", "neutral": "FLAT"}
  print(f"  TOPIX: {mkt['price']:.0f}  SMA50: {mkt['sma50']:.0f}  SMA200: {mkt['sma200']:.0f}  -> {trendEmoji.get(mkt['trend'], '?')}")
  if mkt["trend"] == "down":
    print("  ** Market is in downtrend. Volume Breakout signals will be suppressed.")
  print()

  # 銘柄スクリーニング
  print("[1] Stock screening...")
  stocks = screenStocks(symbols, useJpxList=useJpxList, maxStocks=maxStocks)
  print(f"  -> {len(stocks)} stocks passed\n")

  if not stocks:
    print("No stocks passed screening.")
    return {"stocks": [], "volumeBreakout": [], "bbSqueeze": [], "marketTrend": mkt}

  # トップ10のスコア表示
  print("  Top 10 by score:")
  for s in stocks[:10]:
    sc = s["score"]
    print(f"    {s['symbol']:>8s}  price={s['lastPrice']:>8,.0f}  vol={s['avgVolume']:>10,.0f}"
          f"  RSI={sc['rsi']:.0f}  mom20={sc['momentum20']:>+.1f}%  score={sc['score']:.0f}")
  print()

  # シグナルスキャン
  print("[2] Volume Breakout signals...")
  vbSignals = scanVolumeBreakout(stocks, marketTrend=mkt)
  for s in vbSignals:
    print(f"  ** {s['symbol']}: {s['price']:.0f} - {s['reason']} (score={s['score']:.0f})")
  print(f"  -> {len(vbSignals)} signals\n")

  print("[3] BB Squeeze Breakout signals...")
  bbSignals = scanBBSqueeze(stocks, marketTrend=mkt)
  for s in bbSignals:
    print(f"  ** {s['symbol']}: {s['price']:.0f} - {s['reason']} (score={s['score']:.0f})")
  print(f"  -> {len(bbSignals)} signals\n")

  return {"stocks": stocks, "volumeBreakout": vbSignals, "bbSqueeze": bbSignals, "marketTrend": mkt}


if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser(description="Japanese Small-Cap Screener")
  parser.add_argument("--jpx", action="store_true", help="Use JPX full stock list")
  parser.add_argument("--max", type=int, default=50, help="Max stocks to scan")
  args = parser.parse_args()
  runScreener(useJpxList=args.jpx, maxStocks=args.max)
