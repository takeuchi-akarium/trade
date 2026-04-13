"""ギャップ戦略 負けパターン分析"""
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

nk = fetchOhlcv("^N225", "1d", 3)
nk["sma50"] = nk["close"].rolling(50).mean()
nk["sma200"] = nk["close"].rolling(200).mean()
nk["ret5d"] = nk["close"].pct_change(5) * 100  # 直近5日リターン

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

def getNkRet5d(dt):
  d = dt.date() if hasattr(dt, "date") else dt
  mask = nk.index.date <= d
  if mask.sum() < 6:
    return 0
  return nk[mask]["ret5d"].iloc[-1] if not pd.isna(nk[mask]["ret5d"].iloc[-1]) else 0

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
          "dt": pos["holdStart"], "exitDt": dt, "sym": sym,
          "dir": "long", "reason": exitReason, "pnl": pnl,
          "pnlPct": (sellP - pos["entry"]) / pos["entry"] * 100,
          "capital": cash, "gapPct": pos.get("gapPct", 0),
          "regime": pos.get("regime", "?"),
          "nkRet5d": pos.get("nkRet5d", 0),
          "nHits": pos.get("nHits", 0),
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
          "dt": pos["holdStart"], "exitDt": dt, "sym": sym,
          "dir": "short", "reason": exitReason, "pnl": pnl,
          "pnlPct": (pos["entry"] - coverP) / pos["entry"] * 100,
          "capital": cash, "gapPct": pos.get("gapPct", 0),
          "regime": pos.get("regime", "?"),
          "nkRet5d": pos.get("nkRet5d", 0),
          "nHits": pos.get("nHits", 0),
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

    nHits = len(candidates)
    regime = getRegime(dt)
    nkRet5d = getNkRet5d(dt)

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
            "target": best["target"], "direction": "long",
            "holdStart": dt, "gapPct": best["gap"],
            "regime": regime, "nkRet5d": nkRet5d, "nHits": nHits,
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
            "holdStart": dt, "margin": margin, "gapPct": best["gap"],
            "regime": regime, "nkRet5d": nkRet5d, "nHits": nHits,
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


# === 負けパターン分析 ===
tdf = pd.DataFrame(trades)
lossTrades = tdf[tdf["pnl"] < 0].copy()
winTrades = tdf[tdf["pnl"] >= 0].copy()

print(f"\n=== 負けトレード分析 ({len(lossTrades)}/{len(tdf)} trades) ===\n")

# 1. ギャップサイズ別
print("--- 1. ギャップサイズ別 ---")
bins = [(-100, -5), (-5, -3), (-3, -2), (5, 100)]
labels = ["GD 5%+", "GD 3-5%", "GD 2-3%", "GU 5%+(fade)"]
for (lo, hi), label in zip(bins, labels):
  if lo < 0:
    mask_w = (winTrades["gapPct"] >= lo) & (winTrades["gapPct"] < hi)
    mask_l = (lossTrades["gapPct"] >= lo) & (lossTrades["gapPct"] < hi)
  else:
    mask_w = (winTrades["gapPct"] >= lo) & (winTrades["gapPct"] < hi)
    mask_l = (lossTrades["gapPct"] >= lo) & (lossTrades["gapPct"] < hi)
  w = mask_w.sum()
  l = mask_l.sum()
  total = w + l
  if total == 0:
    continue
  wr = w / total * 100
  avgLoss = lossTrades[mask_l]["pnlPct"].mean() if l > 0 else 0
  print(f"  {label:>12s}: {total:>3d} trades, WR={wr:.1f}%, losses={l}, avg loss={avgLoss:+.2f}%")

# 2. レジーム別
print("\n--- 2. レジーム別 ---")
for regime in ["uptrend", "downtrend", "range"]:
  w = (winTrades["regime"] == regime).sum()
  l = (lossTrades["regime"] == regime).sum()
  total = w + l
  if total == 0:
    continue
  wr = w / total * 100
  lPnl = lossTrades[lossTrades["regime"] == regime]["pnlPct"].mean() if l > 0 else 0
  print(f"  {regime:>12s}: {total:>3d} trades, WR={wr:.1f}%, losses={l}, avg loss={lPnl:+.2f}%")

# 3. 日経5日リターン別（市場の勢い）
print("\n--- 3. 直近5日の日経リターン別 ---")
for lo, hi, label in [(-100, -5, "暴落中(-5%+)"), (-5, -2, "下落中(-2~5%)"), (-2, 0, "小幅安(0~-2%)"), (0, 2, "小幅高(0~+2%)"), (2, 100, "上昇中(+2%+)")]:
  mask_w = (winTrades["nkRet5d"] >= lo) & (winTrades["nkRet5d"] < hi)
  mask_l = (lossTrades["nkRet5d"] >= lo) & (lossTrades["nkRet5d"] < hi)
  w = mask_w.sum()
  l = mask_l.sum()
  total = w + l
  if total == 0:
    continue
  wr = w / total * 100
  print(f"  {label:>18s}: {total:>3d} trades, WR={wr:.1f}%, losses={l}")

# 4. 同時ヒット数別（何銘柄同時にGDしたか）
print("\n--- 4. 同時ヒット数別 ---")
for lo, hi, label in [(1, 2, "1銘柄のみ"), (2, 4, "2-3銘柄"), (4, 7, "4-6銘柄"), (7, 15, "7-14銘柄"), (15, 100, "15銘柄+（暴落日）")]:
  mask_w = (winTrades["nHits"] >= lo) & (winTrades["nHits"] < hi)
  mask_l = (lossTrades["nHits"] >= lo) & (lossTrades["nHits"] < hi)
  w = mask_w.sum()
  l = mask_l.sum()
  total = w + l
  if total == 0:
    continue
  wr = w / total * 100
  avgPnl_w = winTrades[mask_w]["pnlPct"].mean() if w > 0 else 0
  avgPnl_l = lossTrades[mask_l]["pnlPct"].mean() if l > 0 else 0
  print(f"  {label:>18s}: {total:>3d} trades, WR={wr:.1f}%, avgW={avgPnl_w:+.2f}% avgL={avgPnl_l:+.2f}%")

# 5. 銘柄別
print("\n--- 5. 銘柄別 勝率 ---")
symStats = []
for sym in tdf["sym"].unique():
  w = (winTrades["sym"] == sym).sum()
  l = (lossTrades["sym"] == sym).sum()
  total = w + l
  wr = w / total * 100 if total > 0 else 0
  totalPnl = tdf[tdf["sym"] == sym]["pnl"].sum()
  symStats.append((sym, total, wr, totalPnl))
symStats.sort(key=lambda x: x[2])
for sym, n, wr, pnl in symStats:
  marker = " **" if wr < 40 else ""
  print(f"  {sym:>8s}: {n:>3d} trades, WR={wr:>5.1f}%, PnL={pnl:>+10,.0f}{marker}")

# 6. 連敗パターン
print("\n--- 6. 連敗パターン ---")
streak = 0
streakStart = None
streaks = []
for _, t in tdf.iterrows():
  if t["pnl"] <= 0:
    if streak == 0:
      streakStart = t["dt"]
    streak += 1
  else:
    if streak >= 3:
      streaks.append((streakStart, streak, t["dt"]))
    streak = 0

print(f"  3連敗以上の回数: {len(streaks)}")
for start, length, end in sorted(streaks, key=lambda x: -x[1])[:10]:
  startStr = start.strftime("%Y-%m-%d") if hasattr(start, "strftime") else str(start)
  endStr = end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end)
  regime = getRegime(start)
  nkr = getNkRet5d(start)
  print(f"  {length}連敗: {startStr} ~ {endStr} regime={regime} nk5d={nkr:+.1f}%")

# 7. MDD期間の特定
eqArr = np.array([v for _, v in eqList])
peak = np.maximum.accumulate(eqArr)
dd = (eqArr - peak) / peak * 100
mddIdx = np.argmin(dd)
peakIdx = np.argmax(eqArr[:mddIdx + 1])
mddDate = eqList[mddIdx][0]
peakDate = eqList[peakIdx][0]

print(f"\n--- 7. MDD期間 ---")
print(f"  Peak: {peakDate.strftime('%Y-%m-%d')} ({eqArr[peakIdx]:,.0f})")
print(f"  Bottom: {mddDate.strftime('%Y-%m-%d')} ({eqArr[mddIdx]:,.0f})")
print(f"  MDD: {dd[mddIdx]:.1f}%")

# MDD期間中のトレード
mddTrades = tdf[(tdf["dt"] >= peakDate) & (tdf["dt"] <= mddDate)]
if len(mddTrades) > 0:
  print(f"  Trades in MDD period: {len(mddTrades)}")
  mddWins = (mddTrades["pnl"] > 0).sum()
  print(f"  WR during MDD: {mddWins / len(mddTrades) * 100:.1f}%")
  print(f"  Details:")
  for _, t in mddTrades.iterrows():
    dtStr = t["dt"].strftime("%Y-%m-%d") if hasattr(t["dt"], "strftime") else str(t["dt"])
    print(f"    {dtStr} {t['sym']:>8s} gap={t['gapPct']:+.1f}% {t['reason']:>10s} pnl={t['pnlPct']:+.2f}% regime={t['regime']} hits={t['nHits']}")
