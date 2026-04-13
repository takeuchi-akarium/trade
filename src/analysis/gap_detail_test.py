"""ギャップ戦略 詳細分析"""
import sys
sys.path.insert(0, "src")

from strategies.jp_stock.data import fetchOhlcv
from strategies.jp_stock.backtest import calcFee
import numpy as np
import pandas as pd

universe = [
  "6758.T","8306.T","9984.T","7203.T","6501.T","8035.T",
  "9101.T","6098.T","4063.T","8411.T","7974.T","6902.T",
  "3382.T","4568.T","1605.T","5020.T","8604.T","5401.T",
  "7201.T","2413.T","3659.T","1570.T","1357.T",
]

print("Loading data...")
allData = {}
for sym in universe:
  try:
    allData[sym] = fetchOhlcv(sym, "1d", 3)
  except:
    pass
print(f"Loaded: {len(allData)} symbols")

nk = fetchOhlcv("^N225", "1d", 3)
nk["sma50"] = nk["close"].rolling(50).mean()
nk["sma200"] = nk["close"].rolling(200).mean()

regimeCache = {}
def getRegime(dt):
  d = dt.date() if hasattr(dt, "date") else dt
  if d in regimeCache:
    return regimeCache[d]
  mask = nk.index.date <= d
  if mask.sum() < 200:
    regimeCache[d] = "range"
    return "range"
  row = nk[mask].iloc[-1]
  if pd.isna(row["sma200"]):
    r = "range"
  elif row["close"] > row["sma50"] > row["sma200"]:
    r = "uptrend"
  elif row["close"] < row["sma50"] < row["sma200"]:
    r = "downtrend"
  else:
    r = "range"
  regimeCache[d] = r
  return r

allDates = sorted(set().union(*[set(df.index) for df in allData.values()]))

cash = 50000
pos = None
trades = []
eqList = []
SLIP = 0.1
SL_PCT = 1.5

for dt in allDates:
  if pos is not None:
    sym = pos["sym"]
    df = allData[sym]
    if dt not in df.index:
      eqList.append((dt, cash))
      continue
    idx = df.index.get_loc(dt)
    price = df["close"].values[idx]
    high = df["high"].values[idx]
    low = df["low"].values[idx]
    holdDays = (dt - pos["holdStart"]).days

    exitReason = None
    if pos["direction"] == "long":
      if high >= pos["target"]:
        sellP = pos["target"] * (1 - SLIP / 100)
        exitReason = "gap_fill"
      elif low <= pos["entry"] * (1 - SL_PCT / 100):
        sellP = pos["entry"] * (1 - SL_PCT / 100)
        exitReason = "stop_loss"
      elif holdDays >= 3:
        sellP = price * (1 - SLIP / 100)
        exitReason = "time_stop"
      if exitReason:
        proceeds = pos["shares"] * sellP
        fee = calcFee(proceeds)
        pnl = (proceeds - fee) - (pos["shares"] * pos["entry"])
        cash += proceeds - fee
        trades.append({
          "dt": dt, "sym": sym, "dir": "long",
          "reason": exitReason, "pnl": pnl,
          "pnlPct": (sellP - pos["entry"]) / pos["entry"] * 100,
          "capital": cash,
        })
        pos = None
    elif pos["direction"] == "short":
      coverP = 0
      if low <= pos["target"]:
        coverP = pos["target"] * (1 + SLIP / 100)
        exitReason = "gap_fill"
      elif high >= pos["entry"] * (1 + SL_PCT / 100):
        coverP = pos["entry"] * (1 + SL_PCT / 100)
        exitReason = "stop_loss"
      elif holdDays >= 3:
        coverP = price * (1 + SLIP / 100)
        exitReason = "time_stop"
      if exitReason:
        pnl = pos["shares"] * (pos["entry"] - coverP)
        fee = calcFee(pos["shares"] * coverP)
        pnl -= fee
        cash += pos["margin"] + pnl
        trades.append({
          "dt": dt, "sym": sym, "dir": "short",
          "reason": exitReason, "pnl": pnl,
          "pnlPct": (pos["entry"] - coverP) / pos["entry"] * 100,
          "capital": cash,
        })
        pos = None

  if pos is None:
    candidates = []
    for sym, df in allData.items():
      if dt not in df.index:
        continue
      idx = df.index.get_loc(dt)
      if idx < 25:
        continue
      prevClose = df["close"].values[idx - 1]
      todayOpen = df["open"].values[idx]
      if prevClose <= 0:
        continue
      gapPct = (todayOpen - prevClose) / prevClose * 100
      prevVol = df["volume"].values[idx - 1]
      avgVol20 = np.mean(df["volume"].values[max(0, idx - 21):idx - 1]) if idx > 1 else 0

      if gapPct <= -2.0 and avgVol20 > 0 and prevVol >= avgVol20 * 0.8:
        regime = getRegime(dt)
        if gapPct <= -5.0 and regime == "uptrend":
          continue
        candidates.append({
          "sym": sym, "gap": gapPct, "score": abs(gapPct),
          "open": todayOpen, "prevClose": prevClose,
          "direction": "long", "target": prevClose,
        })
      if gapPct >= 5.0:
        candidates.append({
          "sym": sym, "gap": gapPct, "score": abs(gapPct),
          "open": todayOpen, "prevClose": prevClose,
          "direction": "short", "target": prevClose,
        })

    if candidates:
      best = max(candidates, key=lambda x: x["score"])
      sym = best["sym"]
      if best["direction"] == "long":
        buyP = best["open"] * (1 + SLIP / 100)
        inv = cash * 0.95
        fee = calcFee(inv)
        shares = int((inv - fee) / buyP)
        if shares >= 1:
          cash -= shares * buyP + fee
          pos = {
            "sym": sym, "shares": shares, "entry": buyP,
            "target": best["target"], "direction": "long", "holdStart": dt,
          }
      elif best["direction"] == "short":
        sellP = best["open"] * (1 - SLIP / 100)
        inv = cash * 0.95
        shares = int(inv / sellP)
        if shares >= 1:
          margin = shares * sellP
          cash -= margin
          pos = {
            "sym": sym, "shares": shares, "entry": sellP,
            "target": best["target"], "direction": "short",
            "holdStart": dt, "margin": margin,
          }

  val = cash
  if pos is not None:
    sym = pos["sym"]
    df = allData[sym]
    if dt in df.index:
      idx = df.index.get_loc(dt)
      p = df["close"].values[idx]
      if pos["direction"] == "long":
        val = cash + pos["shares"] * p
      else:
        val = cash + pos["margin"] + pos["shares"] * (pos["entry"] - p)
  eqList.append((dt, val))

# === 分析 ===
print(f"\n=== Portfolio Detail (gap largest, 3yr, 50k JPY) ===")
print(f"trades={len(trades)}, final={eqList[-1][1]:,.0f}")

eqS = pd.Series([v for _, v in eqList], index=pd.DatetimeIndex([d for d, _ in eqList]))
monthly = eqS.resample("ME").last()
mret = monthly.pct_change().dropna() * 100
print(f"\nMonthly: mean={mret.mean():+.2f}% std={mret.std():.2f}% max={mret.max():+.2f}% min={mret.min():+.2f}%")
print(f"Monthly win rate: {(mret > 0).mean() * 100:.0f}%")

print("\nYearly returns:")
prev = 50000
for yr in sorted(set(d.year for d, _ in eqList)):
  yrEq = [(d, v) for d, v in eqList if d.year == yr]
  end = yrEq[-1][1]
  ret = (end - prev) / prev * 100
  print(f"  {yr}: {prev:>10,.0f} -> {end:>10,.0f} ({ret:+.1f}%)")
  prev = end

pnls = [t["pnl"] for t in trades]
pnlPcts = [t["pnlPct"] for t in trades]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p <= 0]
winPcts = [p for p in pnlPcts if p > 0]
lossPcts = [p for p in pnlPcts if p <= 0]

print(f"\nWins:   {len(wins)} trades, avg={np.mean(wins):+,.0f}yen ({np.mean(winPcts):+.2f}%)")
print(f"Losses: {len(losses)} trades, avg={np.mean(losses):+,.0f}yen ({np.mean(lossPcts):+.2f}%)")
print(f"PF: {abs(sum(wins) / sum(losses)):.2f}")

eqArr = np.array([v for _, v in eqList])
peak = np.maximum.accumulate(eqArr)
dd = (eqArr - peak) / peak * 100
mdd = dd.min()
print(f"\nMDD: {mdd:.1f}%")

print("\nExit reason breakdown:")
for reason in ["gap_fill", "stop_loss", "time_stop"]:
  rTrades = [t for t in trades if t["reason"] == reason]
  if not rTrades:
    continue
  rPnls = [t["pnl"] for t in rTrades]
  rWins = len([p for p in rPnls if p > 0])
  wr = rWins / len(rTrades) * 100
  print(f"  {reason:>10s}: n={len(rTrades):>3d} WR={wr:.0f}% total={sum(rPnls):+,.0f}yen avg={np.mean(rPnls):+,.0f}")

streak = 0
maxStreak = 0
for t in trades:
  if t["pnl"] <= 0:
    streak += 1
    maxStreak = max(maxStreak, streak)
  else:
    streak = 0
print(f"\nMax consecutive losses: {maxStreak}")

tradeDates = [t["dt"] for t in trades]
gaps = [(tradeDates[i + 1] - tradeDates[i]).days for i in range(len(tradeDates) - 1)]
print(f"Trade interval: mean={np.mean(gaps):.1f}d, median={np.median(gaps):.0f}d")
