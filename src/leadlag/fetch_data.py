"""
日米セクターETFの価格データ取得・キャッシュ

yfinance で Open/Close を取得し、CSV にキャッシュする。
増分更新: 既存CSVがあれば最終日以降のみ追加取得。
"""

import pandas as pd
import yfinance as yf
from pathlib import Path

from leadlag.constants import US_TICKERS, JP_TICKERS


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "leadlag"


def fetchSectorPrices(tickers, cachePath, start="2009-01-01", end=None):
  """
  指定ティッカーの日次 Open/Close を取得し、CSVキャッシュに保存。
  増分更新対応: 既存CSVがあれば最終日翌日から取得して追記。
  """
  cachePath = Path(cachePath)
  cachePath.parent.mkdir(parents=True, exist_ok=True)

  existing = None
  if cachePath.exists():
    existing = pd.read_csv(cachePath, index_col="Date", parse_dates=True)
    lastDate = existing.index.max()
    newStart = (lastDate + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    # end が指定されていて start > end の場合はキャッシュをそのまま返す
    if end and newStart > end:
      return existing
    start = newStart

  raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

  if raw.empty:
    if existing is not None:
      return existing
    return pd.DataFrame()

  # yfinance の MultiIndex columns を処理
  if isinstance(raw.columns, pd.MultiIndex):
    # (Price, Ticker) 形式 → フラット化
    openDf = raw["Open"]
    closeDf = raw["Close"]
  else:
    # 単一ティッカーの場合
    openDf = raw[["Open"]].rename(columns={"Open": tickers[0]})
    closeDf = raw[["Close"]].rename(columns={"Close": tickers[0]})

  # カラム名にプレフィックス付与して結合
  openDf = openDf.copy()
  closeDf = closeDf.copy()
  openDf.columns = [f"Open_{t}" for t in openDf.columns]
  closeDf.columns = [f"Close_{t}" for t in closeDf.columns]
  combined = pd.concat([openDf, closeDf], axis=1)
  combined.index.name = "Date"

  if existing is not None:
    combined = pd.concat([existing, combined])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)

  combined.to_csv(cachePath)
  return combined


def fetchAllPrices(start="2009-01-01", end=None):
  """米国・日本の全セクターETF価格を取得"""
  usPrices = fetchSectorPrices(US_TICKERS, DATA_DIR / "us_sectors.csv", start, end)
  jpPrices = fetchSectorPrices(JP_TICKERS, DATA_DIR / "jp_sectors.csv", start, end)
  return usPrices, jpPrices


def calcCcReturns(prices, tickers):
  """Close-to-Close リターン (PCA推定・シグナル生成用)"""
  closeCols = [f"Close_{t}" for t in tickers]
  available = [c for c in closeCols if c in prices.columns]
  if not available:
    return pd.DataFrame()
  close = prices[available].rename(columns=lambda c: c.replace("Close_", ""))
  returns = close.pct_change().iloc[1:]  # 先頭行(NaN)のみ除去、未上場NaNは保持
  return returns


def calcOcReturns(prices, tickers):
  """Open-to-Close リターン (日本側の戦略評価用: 寄付き→引け)"""
  result = pd.DataFrame(index=prices.index)
  for t in tickers:
    openCol = f"Open_{t}"
    closeCol = f"Close_{t}"
    if openCol in prices.columns and closeCol in prices.columns:
      result[t] = prices[closeCol] / prices[openCol] - 1
  return result.dropna()
