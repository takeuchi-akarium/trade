"""
デュアルモメンタム用の価格データ取得・キャッシュ

yfinance で月次終値を取得し、CSV にキャッシュする。
"""

import pandas as pd
import yfinance as yf
from pathlib import Path

from dual_momentum.constants import ALL_TICKERS

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "dual_momentum"


def fetchPrices(start="2003-01-01", end=None):
  """
  全ETFの月次終値を取得。

  Args:
    start: 取得開始日 (ルックバック期間分の余裕を持たせる)
    end: 取得終了日

  Returns:
    DataFrame: 月末終値 (columns=ティッカー, index=月末日付)
  """
  cachePath = DATA_DIR / "monthly_prices.csv"
  cachePath.parent.mkdir(parents=True, exist_ok=True)

  # キャッシュがあれば読み込み、最終月以降を追加取得
  if cachePath.exists():
    existing = pd.read_csv(cachePath, index_col="Date", parse_dates=True)
    lastDate = existing.index.max()
    newStart = (lastDate + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    kwargs = {"start": newStart}
    if end:
      kwargs["end"] = end

    raw = yf.download(ALL_TICKERS, **kwargs, auto_adjust=True, progress=False)
    if raw.empty or len(raw) < 2:
      return existing

    close = raw["Close"] if len(ALL_TICKERS) > 1 else raw[["Close"]].rename(columns={"Close": ALL_TICKERS[0]})
    monthly = close.resample("ME").last().dropna(how="all")

    if not monthly.empty:
      combined = pd.concat([existing, monthly])
      combined = combined[~combined.index.duplicated(keep="last")]
      combined.sort_index(inplace=True)
      combined.to_csv(cachePath)
      return combined
    return existing

  # 初回取得
  kwargs = {"start": start}
  if end:
    kwargs["end"] = end

  raw = yf.download(ALL_TICKERS, **kwargs, auto_adjust=True, progress=False)
  if raw.empty:
    raise RuntimeError("価格データの取得に失敗しました")

  close = raw["Close"] if len(ALL_TICKERS) > 1 else raw[["Close"]].rename(columns={"Close": ALL_TICKERS[0]})
  monthly = close.resample("ME").last().dropna(how="all")
  monthly.to_csv(cachePath)
  return monthly
