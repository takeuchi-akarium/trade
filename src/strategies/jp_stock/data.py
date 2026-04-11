"""
日本株データ取得

バックテスト用: yfinanceで東証銘柄のOHLCV取得
銘柄ユニバース: JPX公開の上場銘柄一覧から自動構築
将来: 立花証券 e支店 APIに切替
"""

import json
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent.parent.parent
CACHE_DIR = ROOT / "data" / "jp_stock"


def fetchOhlcv(symbol: str, interval: str = "1d", years: int = 3) -> pd.DataFrame:
  """
  東証銘柄のOHLCV取得。

  symbol: "7203.T" (トヨタ), "3782.T" (ディーディーエス) 等
  interval: "1d", "1wk", "1mo"
  years: 取得年数
  """
  periodMap = {1: "1y", 2: "2y", 3: "5y", 5: "5y", 10: "10y"}
  period = periodMap.get(years, f"{years}y")

  ticker = yf.Ticker(symbol)
  df = ticker.history(period=period, interval=interval)

  if df.empty:
    raise ValueError(f"No data for {symbol}")

  df.columns = [c.lower() for c in df.columns]
  df.index.name = "datetime"
  for col in ("dividends", "stock splits", "capital gains", "adj close"):
    df = df.drop(columns=[col], errors="ignore")

  return df[["open", "high", "low", "close", "volume"]]


def fetchMultiple(symbols: list[str], interval: str = "1d", years: int = 3) -> dict[str, pd.DataFrame]:
  """複数銘柄のOHLCVを一括取得"""
  result = {}
  for sym in symbols:
    try:
      result[sym] = fetchOhlcv(sym, interval, years)
    except Exception as e:
      print(f"  [skip] {sym}: {e}")
  return result


# ── JPX銘柄ユニバース ──

JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"


def fetchJpxList(forceRefresh: bool = False) -> pd.DataFrame:
  """
  JPX上場銘柄一覧を取得（1日1回キャッシュ）

  Returns: DataFrame with columns [code, name, market, sector, size]
  """
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  cachePath = CACHE_DIR / "jpx_list.json"

  # キャッシュが今日のものならそれを使う
  if not forceRefresh and cachePath.exists():
    mtime = cachePath.stat().st_mtime
    if time.time() - mtime < 86400:  # 24h
      return pd.DataFrame(json.loads(cachePath.read_text(encoding="utf-8")))

  print("  Fetching JPX stock list...")
  resp = requests.get(JPX_LIST_URL, timeout=30)
  resp.raise_for_status()
  raw = pd.read_excel(BytesIO(resp.content))

  # カラム名はJPXのフォーマット依存
  cols = list(raw.columns)
  df = pd.DataFrame({
    "code": raw[cols[1]].astype(str),
    "name": raw[cols[2]],
    "market": raw[cols[3]],
    "sector": raw[cols[5]],
    "size": raw[cols[9]],
  })

  # キャッシュ保存
  cachePath.write_text(
    json.dumps(df.to_dict(orient="records"), ensure_ascii=False),
    encoding="utf-8",
  )
  return df


def getSmallCapUniverse(
  markets: list[str] = None,
  sizes: list[str] = None,
  excludeSectors: list[str] = None,
) -> list[dict]:
  """
  小型株ユニバースを構築

  Returns: [{"code": "3782", "symbol": "3782.T", "name": "...", "market": "...", "sector": "..."}, ...]
  """
  if markets is None:
    markets = ["スタンダード（内国株式）", "グロース（内国株式）"]
  if sizes is None:
    # TOPIX Small 1/2 または規模区分なし（＝小型）
    sizes = ["TOPIX Small 1", "TOPIX Small 2", "-"]
  if excludeSectors is None:
    excludeSectors = []

  df = fetchJpxList()

  # 市場フィルター
  mask = df["market"].isin(markets)
  # 規模フィルター
  mask &= df["size"].isin(sizes)
  # セクター除外
  if excludeSectors:
    mask &= ~df["sector"].isin(excludeSectors)

  filtered = df[mask].copy()
  filtered["symbol"] = filtered["code"] + ".T"

  result = []
  for _, row in filtered.iterrows():
    result.append({
      "code": row["code"],
      "symbol": row["symbol"],
      "name": row["name"],
      "market": row["market"],
      "sector": row["sector"],
    })

  return result
