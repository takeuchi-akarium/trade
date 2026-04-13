"""ギャップ戦略 銘柄選択ロジック比較"""
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


def runPortfolio(rankFn, label, capital=50000, gdThr=2.0, slPct=1.5, maxHold=3, slip=0.1):
  cash = capital
  pos = None
  trades = []
  eqList = []

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
      sellP = 0
      if pos["direction"] == "long":
        if high >= pos["target"]:
          sellP = pos["target"] * (1 - slip / 100)
          exitReason = "gap_fill"
        elif low <= pos["entry"] * (1 - slPct / 100):
          sellP = pos["entry"] * (1 - slPct / 100)
          exitReason = "stop_loss"
        elif holdDays >= maxHold:
          sellP = price * (1 - slip / 100)
          exitReason = "time_stop"

        if exitReason:
          proceeds = pos["shares"] * sellP
          fee = calcFee(proceeds)
          pnl = (proceeds - fee) - (pos["shares"] * pos["entry"])
          cash += proceeds - fee
          trades.append({"dt": dt, "sym": sym, "dir": "long", "reason": exitReason, "pnl": pnl})
          pos = None

      elif pos["direction"] == "short":
        coverP = 0
        if low <= pos["target"]:
          coverP = pos["target"] * (1 + slip / 100)
          exitReason = "gap_fill"
        elif high >= pos["entry"] * (1 + slPct / 100):
          coverP = pos["entry"] * (1 + slPct / 100)
          exitReason = "stop_loss"
        elif holdDays >= maxHold:
          coverP = price * (1 + slip / 100)
          exitReason = "time_stop"

        if exitReason:
          pnl = pos["shares"] * (pos["entry"] - coverP)
          fee = calcFee(pos["shares"] * coverP)
          pnl -= fee
          cash += pos["margin"] + pnl
          trades.append({"dt": dt, "sym": sym, "dir": "short", "reason": exitReason, "pnl": pnl})
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

        if gapPct <= -gdThr and avgVol20 > 0 and prevVol >= avgVol20 * 0.8:
          regime = getRegime(dt)
          if gapPct <= -5.0 and regime == "uptrend":
            continue
          score = rankFn(gapPct, prevVol, avgVol20, prevClose, df, idx)
          candidates.append({
            "sym": sym, "gap": gapPct, "score": score,
            "open": todayOpen, "prevClose": prevClose,
            "direction": "long", "target": prevClose,
          })

        if gapPct >= 5.0:
          score = rankFn(-gapPct, prevVol, avgVol20, prevClose, df, idx)
          candidates.append({
            "sym": sym, "gap": gapPct, "score": score,
            "open": todayOpen, "prevClose": prevClose,
            "direction": "short", "target": prevClose,
          })

      if candidates:
        best = max(candidates, key=lambda x: x["score"])
        sym = best["sym"]

        if best["direction"] == "long":
          buyP = best["open"] * (1 + slip / 100)
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
          sellP = best["open"] * (1 - slip / 100)
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

  n = len(trades)
  wins = len([t for t in trades if t["pnl"] > 0])
  finalVal = eqList[-1][1] if eqList else capital
  ret = (finalVal - capital) / capital * 100
  wr = wins / n * 100 if n > 0 else 0

  reasons = {}
  for t in trades:
    r = t["reason"]
    reasons[r] = reasons.get(r, 0) + 1

  print(f"\n{label}:")
  print(f"  trades={n}, WR={wr:.1f}%, ret={ret:+.1f}%, final={finalVal:,.0f}")
  print(f"  reasons: {reasons}")
  return trades, eqList


# ランキング関数
rankByGap = lambda gap, vol, avgVol, price, df, idx: abs(gap)

rankByGapVol = lambda gap, vol, avgVol, price, df, idx: abs(gap) * (vol / avgVol if avgVol > 0 else 1)

rankByAffordable = lambda gap, vol, avgVol, price, df, idx: abs(gap) * (1000 / max(price, 100))

def rankByFillHistory(gap, vol, avgVol, price, df, idx):
  fillCount = 0
  total = 0
  o = df["open"].values
  c = df["close"].values
  h = df["high"].values
  for j in range(max(1, idx - 60), idx):
    pc = c[j - 1]
    if pc <= 0:
      continue
    g = (o[j] - pc) / pc * 100
    if g <= -1.5:
      total += 1
      if h[j] >= pc:
        fillCount += 1
  fillRate = fillCount / total if total > 0 else 0.5
  return abs(gap) * (0.5 + fillRate)


print("=== ranking logic comparison (27 symbols, 3yr, 50k JPY) ===")
for fn, label in [
  (rankByGap, "A: gap largest"),
  (rankByGapVol, "B: gap x volume ratio"),
  (rankByAffordable, "C: gap x low price priority"),
  (rankByFillHistory, "D: gap x past fill rate"),
]:
  runPortfolio(fn, label)
