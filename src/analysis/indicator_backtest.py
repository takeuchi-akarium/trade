"""
ファンダメンタル指標のバックテスト
各指標とBTC将来リターンの相関を包括的に分析する
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import requests
import pandas as pd
import numpy as np
import yfinance as yf


def fetchBtc():
  resp = requests.get("https://api.binance.com/api/v3/klines",
    params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000})
  raw = resp.json()
  df = pd.DataFrame(raw, columns=["t","o","h","l","c","v","ct","qv","n","tbv","tqv","ig"])
  df.index = pd.to_datetime(df["t"], unit="ms")
  df["close"] = df["c"].astype(float)
  df["volume"] = df["v"].astype(float)
  df["high"] = df["h"].astype(float)
  df["low"] = df["l"].astype(float)
  return df


def fetchExternal(start, end):
  tickers = {
    "sp500": "^GSPC", "gold": "GC=F", "dxy": "DX-Y.NYB",
    "tnx": "^TNX", "vix": "^VIX", "nasdaq": "^IXIC", "eth": "ETH-USD",
  }
  ext = {}
  for name, ticker in tickers.items():
    try:
      d = yf.download(ticker, start=start, end=end, progress=False)
      if hasattr(d.columns, "get_level_values"):
        d.columns = d.columns.get_level_values(0)
      ext[name] = d["Close"].rename(name)
      print(f"  {name}: {len(ext[name])} days")
    except Exception as e:
      print(f"  {name}: FAILED ({e})")
  return ext


def fetchFng():
  resp = requests.get("https://api.alternative.me/fng/", params={"limit": 1100})
  data = resp.json().get("data", [])
  fng = pd.DataFrame(data)
  fng["date"] = pd.to_datetime(fng["timestamp"].astype(int), unit="s")
  fng["fng"] = fng["value"].astype(int)
  return fng.set_index("date").sort_index()["fng"]


def fetchFunding(startMs, endMs):
  fr_all = []
  cur = startMs
  while cur < endMs:
    resp = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
      params={"symbol": "BTCUSDT", "startTime": cur, "limit": 1000})
    data = resp.json()
    if not data:
      break
    fr_all.extend(data)
    cur = data[-1]["fundingTime"] + 1
  fr = pd.DataFrame(fr_all)
  fr["date"] = pd.to_datetime(fr["fundingTime"], unit="ms")
  fr["rate"] = fr["fundingRate"].astype(float)
  return fr.set_index("date").resample("D")["rate"].mean()


def generateIndicators(df):
  indicators = {}

  # === BTC自身 ===
  # モメンタム（複数期間）
  for p in [5, 10, 20, 30, 50, 100]:
    indicators[f"btc_mom_{p}d"] = df["close"].pct_change(p) * 100

  # MA乖離率
  for p in [20, 50, 100, 200]:
    ma = df["close"].rolling(p).mean()
    indicators[f"btc_sma{p}_dev"] = (df["close"] - ma) / ma * 100

  # MAクロス状態（短期MA - 長期MA の乖離）
  for s, l in [(10, 50), (20, 100), (50, 200)]:
    sma_s = df["close"].rolling(s).mean()
    sma_l = df["close"].rolling(l).mean()
    indicators[f"ma_cross_{s}_{l}"] = (sma_s - sma_l) / sma_l * 100

  # ボラティリティ
  ret = df["close"].pct_change()
  indicators["realized_vol_20"] = ret.rolling(20).std() * np.sqrt(365) * 100
  indicators["realized_vol_60"] = ret.rolling(60).std() * np.sqrt(365) * 100
  indicators["vol_ratio_10_60"] = ret.rolling(10).std() / ret.rolling(60).std()
  indicators["atr_pct_14"] = ((df["high"] - df["low"]) / df["close"]).rolling(14).mean() * 100

  # 出来高
  indicators["vol_sma_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
  indicators["vol_trend"] = df["volume"].rolling(10).mean() / df["volume"].rolling(50).mean()

  # RSI
  delta = df["close"].diff()
  gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
  loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
  rs = gain / loss.replace(0, np.nan)
  indicators["rsi_14"] = 100 - 100 / (1 + rs)

  # 高値/安値からの距離
  indicators["dist_from_20d_high"] = (df["close"] - df["high"].rolling(20).max()) / df["high"].rolling(20).max() * 100
  indicators["dist_from_60d_high"] = (df["close"] - df["high"].rolling(60).max()) / df["high"].rolling(60).max() * 100
  indicators["dist_from_20d_low"] = (df["close"] - df["low"].rolling(20).min()) / df["low"].rolling(20).min() * 100

  # 連続上昇/下落日数
  up = (df["close"] > df["close"].shift(1)).astype(int)
  streak = up.copy()
  for i in range(1, len(streak)):
    if up.iloc[i] == 1:
      streak.iloc[i] = streak.iloc[i-1] + 1
    else:
      streak.iloc[i] = 0
  indicators["up_streak"] = streak

  # === Fear & Greed ===
  if "fng" in df.columns:
    indicators["fng"] = df["fng"]
    indicators["fng_mom_7d"] = df["fng"].diff(7)
    indicators["fng_mom_14d"] = df["fng"].diff(14)
    indicators["fng_sma30_dev"] = df["fng"] - df["fng"].rolling(30).mean()
    # FnG反転: 極端→中央に戻る動き
    indicators["fng_mean_revert"] = df["fng"].rolling(7).mean() - df["fng"].rolling(30).mean()

  # === Funding Rate ===
  if "funding" in df.columns:
    indicators["fr_raw"] = df["funding"]
    indicators["fr_7d_avg"] = df["funding"].rolling(7).mean()
    indicators["fr_7d_sum"] = df["funding"].rolling(7).sum()
    indicators["fr_z_score"] = (df["funding"] - df["funding"].rolling(30).mean()) / df["funding"].rolling(30).std()

  # === クロスアセット ===
  for asset in ["sp500", "gold", "nasdaq", "eth"]:
    if asset not in df.columns:
      continue
    for p in [10, 20, 50]:
      indicators[f"{asset}_mom_{p}d"] = df[asset].pct_change(p) * 100

    # BTC vs asset 相対パフォーマンス
    indicators[f"btc_vs_{asset}_20d"] = (
      df["close"].pct_change(20) - df[asset].pct_change(20)
    ) * 100

  # ETH/BTC ratio（BTCドミナンス代理）
  if "eth" in df.columns:
    ratio = df["eth"] / df["close"]
    indicators["eth_btc_ratio"] = ratio
    indicators["eth_btc_mom_20d"] = ratio.pct_change(20) * 100

  # === DXY ===
  if "dxy" in df.columns:
    indicators["dxy_mom_10d"] = df["dxy"].pct_change(10) * 100
    indicators["dxy_mom_20d"] = df["dxy"].pct_change(20) * 100
    indicators["dxy_sma20_dev"] = (df["dxy"] - df["dxy"].rolling(20).mean()) / df["dxy"].rolling(20).mean() * 100

  # === VIX ===
  if "vix" in df.columns:
    indicators["vix_level"] = df["vix"]
    indicators["vix_sma20_dev"] = (df["vix"] - df["vix"].rolling(20).mean()) / df["vix"].rolling(20).mean() * 100
    indicators["vix_mom_10d"] = df["vix"].diff(10)
    indicators["vix_mom_20d"] = df["vix"].diff(20)
    # VIX term structure proxy: VIX変化速度
    indicators["vix_accel"] = df["vix"].diff().rolling(5).mean()

  # === 金利 ===
  if "tnx" in df.columns:
    indicators["tnx_level"] = df["tnx"]
    indicators["tnx_chg_20d"] = df["tnx"].diff(20)
    indicators["tnx_chg_60d"] = df["tnx"].diff(60)

  # === 複合指標 ===
  # リスクオン指数: BTC + SP500 + Nasdaq のモメンタム平均
  risk_components = []
  for asset in ["close", "sp500", "nasdaq"]:
    if asset in df.columns:
      risk_components.append(df[asset].pct_change(20) * 100)
  if risk_components:
    indicators["risk_on_index"] = pd.concat(risk_components, axis=1).mean(axis=1)

  # マクロ環境スコア: VIX低い + SP500上昇 + ドル安
  if all(x in df.columns for x in ["vix", "sp500", "dxy"]):
    vix_score = -(df["vix"] - 20) / 10  # VIX20を基準に正規化
    sp_score = df["sp500"].pct_change(20) * 100 / 5
    dxy_score = -df["dxy"].pct_change(20) * 100 / 2
    indicators["macro_env_score"] = (vix_score + sp_score + dxy_score) / 3

  return indicators


def main():
  print("=== Fetching data ===")
  btc = fetchBtc()
  print(f"BTC: {btc.index[0].date()} ~ {btc.index[-1].date()} ({len(btc)} days)")

  start = btc.index[0].strftime("%Y-%m-%d")
  end = btc.index[-1].strftime("%Y-%m-%d")

  ext = fetchExternal(start, end)
  fng = fetchFng()
  print(f"  fng: {len(fng)} days")
  funding = fetchFunding(int(btc.index[0].timestamp() * 1000), int(btc.index[-1].timestamp() * 1000))
  print(f"  funding: {len(funding)} days")

  # Forward returns
  for d in [7, 14, 30, 60]:
    btc[f"fwd_{d}d"] = btc["close"].pct_change(d).shift(-d) * 100

  # Merge
  df = btc[["close", "volume", "high", "low", "fwd_7d", "fwd_14d", "fwd_30d", "fwd_60d"]].copy()
  for name, series in ext.items():
    df = df.join(series, how="left")
    df[name] = df[name].ffill()
  df = df.join(fng.rename("fng"), how="left")
  df["fng"] = df["fng"].ffill()
  df = df.join(funding.rename("funding"), how="left")

  # Generate indicators
  indicators = generateIndicators(df)
  print(f"\nGenerated {len(indicators)} indicators")

  # Correlation analysis
  print()
  print("=" * 80)
  print("  ALL INDICATORS vs BTC Forward Return (sorted by |corr 30d|)")
  print("=" * 80)
  print(f"{'indicator':<28} {'fwd7d':>8} {'fwd14d':>8} {'fwd30d':>8} {'fwd60d':>8} {'N':>6}")
  print("-" * 70)

  results = []
  for name, series in indicators.items():
    valid = df[["fwd_7d", "fwd_14d", "fwd_30d", "fwd_60d"]].join(series.rename("ind")).dropna()
    if len(valid) < 50:
      continue
    c7 = valid["ind"].corr(valid["fwd_7d"])
    c14 = valid["ind"].corr(valid["fwd_14d"])
    c30 = valid["ind"].corr(valid["fwd_30d"])
    c60 = valid["ind"].corr(valid["fwd_60d"])
    results.append((name, c7, c14, c30, c60, len(valid)))

  results.sort(key=lambda x: abs(x[3]), reverse=True)
  for name, c7, c14, c30, c60, n in results:
    mark = " ***" if abs(c30) >= 0.25 else (" **" if abs(c30) >= 0.15 else "")
    print(f"{name:<28} {c7:>+7.3f} {c14:>+7.3f} {c30:>+7.3f} {c60:>+7.3f} {n:>6}{mark}")

  # Top indicators: quintile analysis
  print()
  print("=" * 80)
  print("  TOP INDICATORS: Quintile Analysis (avg fwd return per quintile)")
  print("=" * 80)

  top_indicators = [r[0] for r in results[:8]]
  for ind_name in top_indicators:
    series = indicators[ind_name]
    valid = df[["fwd_7d", "fwd_14d", "fwd_30d"]].join(series.rename("ind")).dropna()
    if len(valid) < 50:
      continue

    valid = valid.copy()
    try:
      valid["q"] = pd.qcut(valid["ind"], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"], duplicates="drop")
    except ValueError:
      continue

    print(f"\n  {ind_name}")
    print(f"  {'quintile':<8} {'avg_val':>10} {'fwd_7d':>10} {'fwd_14d':>10} {'fwd_30d':>10} {'N':>6}")
    print(f"  {'-' * 58}")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
      g = valid[valid["q"] == q]
      if len(g) == 0:
        continue
      print(f"  {q:<8} {g['ind'].mean():>+9.2f} {g['fwd_7d'].mean():>+9.2f}% {g['fwd_14d'].mean():>+9.2f}% {g['fwd_30d'].mean():>+9.2f}% {len(g):>6}")


if __name__ == "__main__":
  main()
