"""複利効果の検証: ファンダ補正で底値の資金が増えれば回復時に有利か？"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import requests, pandas as pd, numpy as np, yfinance as yf
from strategies.scalping.strategies import calcBb, calcEma
from strategies.scalping.backtest import runBacktest, runBacktestLongShort

# === データ取得 ===
resp = requests.get("https://api.binance.com/api/v3/klines",
  params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000})
raw = resp.json()
btc = pd.DataFrame(raw, columns=["t","o","h","l","c","v","ct","qv","n","tbv","tqv","ig"])
btc.index = pd.to_datetime(btc["t"], unit="ms")
for col in ["open","high","low","close","volume"]:
  btc[col] = btc[col[0]].astype(float) if col != "volume" else btc["v"].astype(float)
start, end = btc.index[0].strftime("%Y-%m-%d"), btc.index[-1].strftime("%Y-%m-%d")

gold = yf.download("GC=F", start=start, end=end, progress=False)
tnx = yf.download("^TNX", start=start, end=end, progress=False)
if hasattr(gold.columns, "get_level_values"): gold.columns = gold.columns.get_level_values(0)
if hasattr(tnx.columns, "get_level_values"): tnx.columns = tnx.columns.get_level_values(0)
resp2 = requests.get("https://api.alternative.me/fng/", params={"limit": 1100})
fng = pd.DataFrame(resp2.json().get("data", []))
fng["date"] = pd.to_datetime(fng["timestamp"].astype(int), unit="s")
fng["fng"] = fng["value"].astype(int)
fng = fng.set_index("date").sort_index()["fng"]

df = btc[["open","high","low","close","volume"]].copy()
df = df.join(gold["Close"].rename("gold"), how="left")
df = df.join(tnx["Close"].rename("tnx"), how="left")
df = df.join(fng, how="left")
df["gold"] = df["gold"].ffill()
df["tnx"] = df["tnx"].ffill()
df["fng"] = df["fng"].ffill()

# ファンダスコア
g = df["gold"].pct_change(50) * 100
t = df["tnx"].diff(20)
f = df["fng"].rolling(7).mean() - df["fng"].rolling(30).mean()
w = 90
gold_z = -(g - g.rolling(w).mean()) / g.rolling(w).std()
tnx_z = (t - t.rolling(w).mean()) / t.rolling(w).std()
fng_z = (f - f.rolling(w).mean()) / f.rolling(w).std()
df["funda"] = 0.41 * gold_z + 0.37 * tnx_z + 0.22 * fng_z

# SMA50レジーム
sma50 = df["close"].rolling(50).mean()
df["regime"] = "range"
df.loc[df["close"] > sma50 * 1.02, "regime"] = "uptrend"
df.loc[df["close"] < sma50 * 0.98, "regime"] = "downtrend"

# 戦略equity
cap = 100_000
fee = 0.1
dfBb = calcBb(df, period=20, std=2.0)
dfEma = calcEma(df, short=10, long=50)
dfBbLs = calcBb(df, period=20, std=2.0)
_, eqBb = runBacktest(dfBb, cap, fee / 100)
_, eqEma = runBacktest(dfEma, cap, fee / 100)
_, eqBbLs = runBacktestLongShort(dfBbLs, cap, fee / 100, stopLossPct=5.0)
retBb = eqBb.pct_change().fillna(0)
retEma = eqEma.pct_change().fillna(0)
retBbLs = eqBbLs.pct_change().fillna(0)


def simulate(getWeights):
  equity = cap
  eqList = []
  prevR = None
  for i in range(len(df)):
    regime = df["regime"].iloc[i]
    funda = df["funda"].iloc[i]
    wBb, wEma, wLs = getWeights(regime, funda)
    if prevR is not None and regime != prevR:
      equity -= equity * fee / 100 * 2
    rB = retBb.iloc[i] if i < len(retBb) else 0
    rE = retEma.iloc[i] if i < len(retEma) else 0
    rL = retBbLs.iloc[i] if i < len(retBbLs) else 0
    equity *= (1 + wBb * rB + wEma * rE + wLs * rL)
    eqList.append(equity)
    prevR = regime
  return pd.Series(eqList, index=df.index)


def current(r, f):
  if r == "uptrend": return (0.30, 0.70, 0.00)
  if r == "range":   return (0.70, 0.10, 0.20)
  return (0.00, 0.00, 0.00)


def disagree(r, f):
  base = current(r, f)
  if pd.isna(f): return base
  tech_bull = (r == "uptrend")
  tech_bear = (r == "downtrend")
  funda_bull = (f > 0.5)
  funda_bear = (f < -0.5)
  if not ((tech_bull and funda_bear) or (tech_bear and funda_bull) or
          (r == "range" and (funda_bull or funda_bear))):
    return base
  if tech_bull and funda_bear:
    return (0.15, 0.35, 0.00)
  if tech_bear and funda_bull:
    return (0.12, 0.18, 0.00)
  if r == "range" and funda_bull:
    return (0.50, 0.30, 0.20)
  if r == "range" and funda_bear:
    return (0.60, 0.00, 0.10)
  return base


eq1 = simulate(current)
eq2 = simulate(disagree)

# === 月次equity比較 ===
print("=" * 80)
print("  Monthly Equity Comparison")
print("=" * 80)
print(f"  {'month':<10} {'BTC':>10} {'regime':<10} {'funda':>7} {'tech_eq':>12} {'disagree_eq':>12} {'diff':>8}")
print(f"  {'-' * 72}")

monthly = df.resample("MS").first()
for date in monthly.index:
  if date not in eq1.index:
    continue
  r = df.loc[date, "regime"]
  fv = df.loc[date, "funda"]
  fs = f"{fv:+.1f}" if not pd.isna(fv) else "  N/A"
  e1 = eq1.loc[date]
  e2 = eq2.loc[date]
  diff = (e2 - e1) / e1 * 100
  print(f"  {date.strftime('%Y-%m'):<10} {df.loc[date, 'close']:>10,.0f} {r:<10} {fs:>7} {e1:>11,.0f} {e2:>11,.0f} {diff:>+7.1f}%")

# === ドローダウン比較 ===
print()
print("=" * 80)
print("  Drawdown at Worst Points")
print("=" * 80)
peak1 = eq1.expanding().max()
dd1 = (eq1 - peak1) / peak1 * 100
peak2 = eq2.expanding().max()
dd2 = (eq2 - peak2) / peak2 * 100

# BTC大暴落期間を特定
btc_peak_idx = df["close"].idxmax()
btc_bottom_idx = df.loc[btc_peak_idx:, "close"].idxmin()
print(f"  BTC peak:   {btc_peak_idx.strftime('%Y-%m-%d')} = ${df.loc[btc_peak_idx, 'close']:,.0f}")
print(f"  BTC bottom: {btc_bottom_idx.strftime('%Y-%m-%d')} = ${df.loc[btc_bottom_idx, 'close']:,.0f} ({(df.loc[btc_bottom_idx, 'close'] / df.loc[btc_peak_idx, 'close'] - 1) * 100:+.1f}%)")
print()
print(f"  {'point':<20} {'tech_eq':>12} {'disagree_eq':>12} {'diff':>12}")
print(f"  {'-' * 58}")
print(f"  {'At BTC peak':<20} {eq1[btc_peak_idx]:>11,.0f} {eq2[btc_peak_idx]:>11,.0f} {(eq2[btc_peak_idx] - eq1[btc_peak_idx]):>+11,.0f}")
print(f"  {'At BTC bottom':<20} {eq1[btc_bottom_idx]:>11,.0f} {eq2[btc_bottom_idx]:>11,.0f} {(eq2[btc_bottom_idx] - eq1[btc_bottom_idx]):>+11,.0f}")

# 底値から回復
after1 = eq1.loc[btc_bottom_idx:]
after2 = eq2.loc[btc_bottom_idx:]
for days in [30, 60, 90, 120]:
  if len(after1) > days:
    r1 = (after1.iloc[days] - after1.iloc[0]) / after1.iloc[0] * 100
    r2 = (after2.iloc[days] - after2.iloc[0]) / after2.iloc[0] * 100
    print(f"  {'Recovery +' + str(days) + 'd':<20} {after1.iloc[days]:>11,.0f} {after2.iloc[days]:>11,.0f} {(after2.iloc[days] - after1.iloc[days]):>+11,.0f}")

print(f"  {'Final':<20} {eq1.iloc[-1]:>11,.0f} {eq2.iloc[-1]:>11,.0f} {(eq2.iloc[-1] - eq1.iloc[-1]):>+11,.0f}")

# 複利効果の計算
print()
print("=" * 80)
print("  Compound Effect Analysis")
print("=" * 80)
eq1_bottom = eq1[btc_bottom_idx]
eq2_bottom = eq2[btc_bottom_idx]
capital_advantage = eq2_bottom - eq1_bottom
print(f"  Capital at bottom: tech={eq1_bottom:,.0f}, disagree={eq2_bottom:,.0f}")
print(f"  Advantage at bottom: {capital_advantage:+,.0f} ({capital_advantage / eq1_bottom * 100:+.1f}%)")

if len(after1) > 60:
  # 底値から最終日までのリターン（%）は同じはず（同じ戦略を使うため）
  # でも起点の資金が違う → 絶対額に差が出る
  recovery_ret1 = (eq1.iloc[-1] - eq1_bottom) / eq1_bottom * 100
  recovery_ret2 = (eq2.iloc[-1] - eq2_bottom) / eq2_bottom * 100
  print(f"  Recovery return: tech={recovery_ret1:+.1f}%, disagree={recovery_ret2:+.1f}%")
  # 仮にdisagreeが底値で持っていた資金にtechの回復率を適用したら？
  hypothetical = eq2_bottom * (1 + recovery_ret1 / 100)
  print(f"  If disagree capital earned tech recovery rate: {hypothetical:,.0f}")
  print(f"  vs actual disagree final: {eq2.iloc[-1]:,.0f}")
  print(f"  vs actual tech final: {eq1.iloc[-1]:,.0f}")

# どちらが勝っている日数
wins = (eq2 > eq1).sum()
total = len(eq1)
print(f"\n  Days disagree > tech: {wins}/{total} ({wins / total * 100:.1f}%)")
