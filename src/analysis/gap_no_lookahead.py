"""ギャップ戦略: 事前に知れる情報だけで負けを予測できるか

エントリー判断時に使える情報:
  [OK] 前日までの出来高推移
  [OK] 前日までの株価モメンタム
  [OK] 日経先物/前日終値（レジーム）
  [OK] GDの大きさ（寄り付き値は見える）
  [OK] 同時にGDしている銘柄数（板情報から推定可能）
  [NG] 当日の出来高 ← 使えない
  [NG] 当日の高値/安値 ← 使えない
"""
import sys
sys.path.insert(0, "src")

from strategies.jp_stock.data import fetchOhlcv
import numpy as np
import pandas as pd

universe = [
  "6758.T","8306.T","9984.T","7203.T","6501.T","8035.T",
  "9101.T","6098.T","4063.T","8411.T","7974.T","6902.T",
  "3382.T","4568.T","1605.T","5020.T","8604.T","5401.T",
  "7201.T","2413.T","3659.T","1570.T","1357.T",
]

print("Loading...")
allData = {}
for sym in universe:
  try:
    allData[sym] = fetchOhlcv(sym, "1d", 3)
  except:
    pass

nk = fetchOhlcv("^N225", "1d", 3)
nk["ret1d"] = nk["close"].pct_change() * 100
nk["ret5d"] = nk["close"].pct_change(5) * 100
nk["sma50"] = nk["close"].rolling(50).mean()
nk["sma200"] = nk["close"].rolling(200).mean()

# GDイベント収集（事前に知れる情報のみ）
events = []
for sym, df in allData.items():
  o = df["open"].values
  c = df["close"].values
  h = df["high"].values
  l = df["low"].values
  v = df["volume"].values
  dates = df.index

  for i in range(25, len(df)):
    prev = c[i - 1]
    if prev <= 0:
      continue
    gapPct = (o[i] - prev) / prev * 100
    if gapPct > -2.0:
      continue

    # 窓埋め判定（3日以内）
    filled = False
    for j in range(i, min(i + 3, len(df))):
      if h[j] >= prev:
        filled = True
        break

    # === 事前に知れる情報のみ ===
    # 前日までのモメンタム
    mom5 = (c[i - 1] - c[i - 6]) / c[i - 6] * 100 if i >= 6 else 0
    mom20 = (c[i - 1] - c[i - 21]) / c[i - 21] * 100 if i >= 21 else 0

    # 前日の出来高トレンド（前日 vs 20日平均）
    avgVol20 = np.mean(v[max(0, i - 21):i - 1]) if i > 1 else 1
    prevVolRatio = v[i - 1] / avgVol20 if avgVol20 > 0 else 1

    # 直近5日の出来高トレンド（増加傾向か）
    vol5 = np.mean(v[max(0, i - 5):i]) if i >= 5 else avgVol20
    volTrend5 = vol5 / avgVol20 if avgVol20 > 0 else 1

    # 前日のATR（ボラティリティ）
    atrList = []
    for j in range(max(1, i - 14), i):
      tr = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
      atrList.append(tr)
    atr = np.mean(atrList) if atrList else 0
    atrPct = atr / prev * 100 if prev > 0 else 0

    # 過去60日のギャップフィル率（この銘柄固有）
    fillCount = 0
    gdCount = 0
    for j in range(max(1, i - 60), i):
      pc = c[j - 1]
      if pc <= 0:
        continue
      g = (o[j] - pc) / pc * 100
      if g <= -1.5:
        gdCount += 1
        if h[j] >= pc or (j + 1 < len(df) and h[j + 1] >= pc):
          fillCount += 1
    histFillRate = fillCount / gdCount if gdCount > 0 else 0.5

    # 日経の状態（前日時点）
    nkMask = nk.index < dates[i]
    if nkMask.sum() > 0:
      nkPrev = nk[nkMask].iloc[-1]
      nkRet1d = nkPrev["ret1d"] if not pd.isna(nkPrev["ret1d"]) else 0
      nkRet5d = nkPrev["ret5d"] if not pd.isna(nkPrev["ret5d"]) else 0
    else:
      nkRet1d = 0
      nkRet5d = 0

    # 同時GD数
    nHits = 0
    for s2, df2 in allData.items():
      if dates[i] not in df2.index:
        continue
      idx2 = df2.index.get_loc(dates[i])
      if idx2 < 1:
        continue
      pc2 = df2["close"].values[idx2 - 1]
      if pc2 <= 0:
        continue
      g2 = (df2["open"].values[idx2] - pc2) / pc2 * 100
      if g2 <= -2.0:
        nHits += 1

    events.append({
      "sym": sym, "date": dates[i], "gapPct": gapPct,
      "filled": filled,
      "mom5": mom5, "mom20": mom20,
      "prevVolRatio": prevVolRatio, "volTrend5": volTrend5,
      "atrPct": atrPct, "histFillRate": histFillRate,
      "nkRet1d": nkRet1d, "nkRet5d": nkRet5d,
      "nHits": nHits,
    })

edf = pd.DataFrame(events)
baseFr = edf["filled"].mean() * 100
print(f"\nTotal: {len(edf)} events, base fill rate: {baseFr:.1f}%\n")

# === 事前情報のみで予測力を検証 ===
print("=" * 70)
print("事前に知れる情報のみで窓埋め率を予測できるか")
print("=" * 70)

print("\n--- 前日出来高（前日 vs 20日平均）---")
for lo, hi, label in [(0, 0.5, "前日出来高 少(<0.5x)"),
                       (0.5, 1.0, "前日出来高 通常以下"),
                       (1.0, 2.0, "前日出来高 通常"),
                       (2.0, 5.0, "前日出来高 多い(2-5x)"),
                       (5.0, 1000, "前日出来高 急増(5x+)")]:
  mask = (edf["prevVolRatio"] >= lo) & (edf["prevVolRatio"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- 5日出来高トレンド ---")
for lo, hi, label in [(0, 0.8, "出来高減少傾向(<0.8x)"),
                       (0.8, 1.2, "出来高安定"),
                       (1.2, 2.0, "出来高増加傾向"),
                       (2.0, 1000, "出来高急増傾向(2x+)")]:
  mask = (edf["volTrend5"] >= lo) & (edf["volTrend5"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- 前5日モメンタム ---")
for lo, hi, label in [(-100, -5, "急落中(<-5%)"),
                       (-5, -1, "下落中(-5~-1%)"),
                       (-1, 1, "横ばい"),
                       (1, 5, "上昇中(+1~+5%)"),
                       (5, 100, "急騰中(>+5%)")]:
  mask = (edf["mom5"] >= lo) & (edf["mom5"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- 過去のギャップフィル率（銘柄固有）---")
for lo, hi, label in [(0, 0.2, "フィル率 低(<20%)"),
                       (0.2, 0.4, "フィル率 中低(20-40%)"),
                       (0.4, 0.6, "フィル率 中(40-60%)"),
                       (0.6, 1.01, "フィル率 高(60%+)")]:
  mask = (edf["histFillRate"] >= lo) & (edf["histFillRate"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- ギャップサイズ ---")
for lo, hi, label in [(-3, -2, "GD 2-3%"),
                       (-5, -3, "GD 3-5%"),
                       (-10, -5, "GD 5-10%"),
                       (-100, -10, "GD 10%+")]:
  mask = (edf["gapPct"] >= lo) & (edf["gapPct"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- 同時GD数 ---")
for lo, hi, label in [(1, 2, "1銘柄のみ"),
                       (2, 4, "2-3銘柄"),
                       (4, 8, "4-7銘柄"),
                       (8, 15, "8-14銘柄"),
                       (15, 100, "15+銘柄")]:
  mask = (edf["nHits"] >= lo) & (edf["nHits"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

print("\n--- ATR（ボラティリティ）---")
for lo, hi, label in [(0, 1.5, "低ボラ(<1.5%)"),
                       (1.5, 3.0, "中ボラ"),
                       (3.0, 5.0, "高ボラ"),
                       (5.0, 100, "超高ボラ(5%+)")]:
  mask = (edf["atrPct"] >= lo) & (edf["atrPct"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  print(f"  {label:>25s}: n={n:>4d}  fill={fr:>5.1f}%  {diff:>+5.1f}%")

# === 組合せ: 事前情報のみで最良/最悪を特定 ===
print("\n" + "=" * 70)
print("事前情報の組合せで最良/最悪の条件")
print("=" * 70)

combos = [
  ("GD大(5%+) + 前日vol少(<1x)", (edf["gapPct"] <= -5) & (edf["prevVolRatio"] < 1)),
  ("GD大(5%+) + 前日vol多(>2x)", (edf["gapPct"] <= -5) & (edf["prevVolRatio"] > 2)),
  ("mom5下落 + 前日vol少", (edf["mom5"] < -1) & (edf["prevVolRatio"] < 1)),
  ("mom5上昇 + 前日vol多", (edf["mom5"] > 1) & (edf["prevVolRatio"] > 2)),
  ("histFill高 + 前日vol少", (edf["histFillRate"] > 0.5) & (edf["prevVolRatio"] < 1)),
  ("histFill低 + 前日vol多", (edf["histFillRate"] < 0.3) & (edf["prevVolRatio"] > 2)),
  ("GD大 + histFill高", (edf["gapPct"] <= -5) & (edf["histFillRate"] > 0.5)),
  ("GD大 + histFill低", (edf["gapPct"] <= -5) & (edf["histFillRate"] < 0.3)),
  ("1銘柄のみ + vol少", (edf["nHits"] == 1) & (edf["prevVolRatio"] < 1)),
  ("8-14銘柄 + vol多", (edf["nHits"] >= 8) & (edf["nHits"] < 15) & (edf["prevVolRatio"] > 2)),
  ("15+ + GD大(5%+)", (edf["nHits"] >= 15) & (edf["gapPct"] <= -5)),
  ("mom5上昇 + 8-14銘柄", (edf["mom5"] > 1) & (edf["nHits"] >= 8) & (edf["nHits"] < 15)),
  ("ATR高 + vol多", (edf["atrPct"] > 3) & (edf["prevVolRatio"] > 2)),
  ("ATR低 + vol少", (edf["atrPct"] < 2) & (edf["prevVolRatio"] < 1)),
  ("全条件SAFE: GD大+vol少+histFill高", (edf["gapPct"] <= -5) & (edf["prevVolRatio"] < 1) & (edf["histFillRate"] > 0.4)),
  ("全条件DANGER: mom5上昇+vol多+8-14銘柄", (edf["mom5"] > 1) & (edf["prevVolRatio"] > 2) & (edf["nHits"] >= 8) & (edf["nHits"] < 15)),
]

print(f"\n{'条件':>40s}  {'n':>5s}  {'fill%':>6s}  {'vs base':>8s}")
print("-" * 65)
for name, mask in combos:
  n = mask.sum()
  if n < 5:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  marker = " <-- DANGER" if diff < -8 else (" <-- SAFE" if diff > 8 else "")
  print(f"  {name:>38s}  {n:>5d}  {fr:>5.1f}%  {diff:>+6.1f}%{marker}")
