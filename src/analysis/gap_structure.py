"""ギャップ戦略 負けの構造分析

「なぜ窓が埋まらないのか」を体系的に分類する。
GDが発生した日の前後の市場・銘柄の状態から負けの原因構造を特定する。
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
nk["sma50"] = nk["close"].rolling(50).mean()
nk["sma200"] = nk["close"].rolling(200).mean()
nk["ret1d"] = nk["close"].pct_change() * 100
nk["ret5d"] = nk["close"].pct_change(5) * 100

# 全GD 2%+イベントを収集し、3日以内に窓埋めしたかを判定
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

    # 窓埋め判定（3日以内に高値がprevCloseに到達）
    filled = False
    fillDay = -1
    for j in range(i, min(i + 3, len(df))):
      if h[j] >= prev:
        filled = True
        fillDay = j - i
        break

    # 当日の動き
    intraDayRet = (c[i] - o[i]) / o[i] * 100  # 始値→終値
    intraDayRange = (h[i] - l[i]) / o[i] * 100  # 日中レンジ

    # --- 前後の文脈 ---
    # A: エントリー前の株価トレンド（5日・20日モメンタム）
    mom5 = (c[i - 1] - c[i - 6]) / c[i - 6] * 100 if i >= 6 else 0
    mom20 = (c[i - 1] - c[i - 21]) / c[i - 21] * 100 if i >= 21 else 0

    # B: 出来高の変化（当日 vs 20日平均）
    avgVol20 = np.mean(v[max(0, i - 21):i - 1]) if i > 1 else 1
    volRatio = v[i] / avgVol20 if avgVol20 > 0 else 1

    # C: GD後の動き（始値からの方向）
    openToHigh = (h[i] - o[i]) / o[i] * 100  # 始値→高値（戻り力）
    openToLow = (o[i] - l[i]) / o[i] * 100    # 始値→安値（さらなる下落）

    # D: 日経の状態
    nkMask = nk.index <= dates[i]
    nkRow = nk[nkMask].iloc[-1] if nkMask.sum() > 0 else None
    nkRet1d = nkRow["ret1d"] if nkRow is not None and not pd.isna(nkRow["ret1d"]) else 0
    nkRet5d = nkRow["ret5d"] if nkRow is not None and not pd.isna(nkRow["ret5d"]) else 0

    # E: 同日に他に何銘柄GDしたか
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
      "filled": filled, "fillDay": fillDay,
      "intraDayRet": intraDayRet, "intraDayRange": intraDayRange,
      "mom5": mom5, "mom20": mom20,
      "volRatio": volRatio,
      "openToHigh": openToHigh, "openToLow": openToLow,
      "nkRet1d": nkRet1d, "nkRet5d": nkRet5d,
      "nHits": nHits,
    })

edf = pd.DataFrame(events)
wins = edf[edf["filled"]]
losses = edf[~edf["filled"]]

print(f"\nTotal GD events: {len(edf)} (filled: {len(wins)}, not filled: {len(losses)})")
print(f"Overall fill rate: {len(wins)/len(edf)*100:.1f}%")

# === 構造分析 ===
print("\n" + "=" * 70)
print("=== 負けの構造分析: なぜ窓が埋まらないのか ===")
print("=" * 70)

# --- 構造1: GD前のモメンタム ---
print("\n--- 構造1: GD前の株価トレンド ---")
print("（GD前に上がっていたか、下がっていたか）")
for lo, hi, label in [(-100, -5, "急落中(mom5<-5%)"), (-5, -1, "下落中(-5~-1%)"),
                       (-1, 1, "横ばい(-1~+1%)"), (1, 5, "上昇中(+1~+5%)"), (5, 100, "急騰中(mom5>+5%)")]:
  mask = (edf["mom5"] >= lo) & (edf["mom5"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  avgGap = edf[mask]["gapPct"].mean()
  print(f"  {label:>22s}: n={n:>4d}  fill rate={fr:>5.1f}%  avg gap={avgGap:+.1f}%")

# --- 構造2: 出来高 ---
print("\n--- 構造2: GD当日の出来高（20日平均比）---")
print("（出来高が多い=本気の売り、少ない=一時的な需給）")
for lo, hi, label in [(0, 0.5, "極少(<0.5x)"), (0.5, 1.0, "通常以下(0.5-1x)"),
                       (1.0, 2.0, "通常～2倍"), (2.0, 5.0, "急増(2-5x)"), (5.0, 1000, "爆増(5x+)")]:
  mask = (edf["volRatio"] >= lo) & (edf["volRatio"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  print(f"  {label:>18s}: n={n:>4d}  fill rate={fr:>5.1f}%")

# --- 構造3: GD当日の値動きパターン ---
print("\n--- 構造3: GD当日の値動き ---")
print("（寄り付き後にどう動いたか）")

# 始値→高値（戻り力）と始値→安値（追加下落）のバランス
for lo, hi, label in [(0, 0.5, "戻り力 弱(<0.5%)"), (0.5, 1.5, "戻り力 中(0.5-1.5%)"),
                       (1.5, 3.0, "戻り力 強(1.5-3%)"), (3.0, 100, "戻り力 超強(3%+)")]:
  mask = (edf["openToHigh"] >= lo) & (edf["openToHigh"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  print(f"  {label:>25s}: n={n:>4d}  fill rate={fr:>5.1f}%")

# --- 構造4: 市場連動性 ---
print("\n--- 構造4: 日経の状態 ---")
print("（個別要因のGDか、市場全体の売りか）")
for lo, hi, label in [(-100, -2, "日経急落(1d<-2%)"), (-2, -0.5, "日経下落(-2~-0.5%)"),
                       (-0.5, 0.5, "日経横ばい"), (0.5, 2, "日経上昇(+0.5~2%)"), (2, 100, "日経急騰(1d>+2%)")]:
  mask = (edf["nkRet1d"] >= lo) & (edf["nkRet1d"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  wFr = wins[wins.index.isin(edf[mask].index)]["fillDay"].value_counts().sort_index() if mask.sum() > 0 else {}
  print(f"  {label:>22s}: n={n:>4d}  fill rate={fr:>5.1f}%")

# --- 構造5: 個別GD vs 全体GD ---
print("\n--- 構造5: 個別GD vs 全体GD ---")
print("（自分だけ下がったのか、みんな下がったのか）")
for lo, hi, label in [(1, 2, "1銘柄のみ（個別要因）"), (2, 4, "2-3銘柄"), (4, 8, "4-7銘柄（セクター売り？）"),
                       (8, 15, "8-14銘柄（全体売り）"), (15, 100, "15+銘柄（パニック売り）")]:
  mask = (edf["nHits"] >= lo) & (edf["nHits"] < hi)
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  avgGap = edf[mask]["gapPct"].mean()
  print(f"  {label:>25s}: n={n:>4d}  fill rate={fr:>5.1f}%  avg gap={avgGap:+.1f}%")

# --- 構造6: ギャップの「質」 ---
print("\n--- 構造6: ギャップの質（サイズ x 出来高の組合せ）---")
print("（大きいGD + 出来高少ない = 需給歪み → 埋まりやすい?）")
print("（大きいGD + 出来高多い = 本気の売り → 埋まりにくい?）")
for gLo, gHi, gLabel in [(-5, -2, "GD 2-5%"), (-100, -5, "GD 5%+")]:
  for vLo, vHi, vLabel in [(0, 1.5, "出来高少"), (1.5, 3.0, "出来高中"), (3.0, 1000, "出来高大")]:
    mask = (edf["gapPct"] >= gLo) & (edf["gapPct"] < gHi) & (edf["volRatio"] >= vLo) & (edf["volRatio"] < vHi)
    n = mask.sum()
    if n < 5:
      continue
    fr = edf[mask]["filled"].mean() * 100
    print(f"  {gLabel:>8s} + {vLabel}: n={n:>4d}  fill rate={fr:>5.1f}%")

# --- 最終まとめ: 負けやすい条件の組合せ ---
print("\n" + "=" * 70)
print("=== 負けやすい条件の組合せ ===")
print("=" * 70)

# 各要因を組合せてfill rateを見る
conditions = {
  "GD前5日上昇(>+1%)": edf["mom5"] > 1,
  "GD前5日下落(<-1%)": edf["mom5"] < -1,
  "出来高急増(>2x)": edf["volRatio"] > 2,
  "出来高通常以下(<1x)": edf["volRatio"] < 1,
  "日経当日下落(<-1%)": edf["nkRet1d"] < -1,
  "日経当日上昇(>+0.5%)": edf["nkRet1d"] > 0.5,
  "同時ヒット1のみ": edf["nHits"] == 1,
  "同時ヒット2-6": (edf["nHits"] >= 2) & (edf["nHits"] <= 6),
  "同時ヒット7+": edf["nHits"] >= 7,
}

print(f"\n{'条件':>30s}  {'n':>5s}  {'fill%':>6s}  {'vs全体':>8s}")
print("-" * 55)
baseFr = edf["filled"].mean() * 100
for name, mask in conditions.items():
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  marker = " !!" if diff < -5 else (" ++" if diff > 5 else "")
  print(f"  {name:>28s}  {n:>5d}  {fr:>5.1f}%  {diff:>+6.1f}%{marker}")

# 二重条件
print("\n--- 二重条件（最も危険な組合せ）---")
combos = [
  ("前5日上昇 + 出来高急増", (edf["mom5"] > 1) & (edf["volRatio"] > 2)),
  ("前5日上昇 + 同時2-6", (edf["mom5"] > 1) & (edf["nHits"] >= 2) & (edf["nHits"] <= 6)),
  ("前5日下落 + 同時2-6", (edf["mom5"] < -1) & (edf["nHits"] >= 2) & (edf["nHits"] <= 6)),
  ("出来高急増 + 同時2-6", (edf["volRatio"] > 2) & (edf["nHits"] >= 2) & (edf["nHits"] <= 6)),
  ("日経上昇 + 同時1のみ", (edf["nkRet1d"] > 0.5) & (edf["nHits"] == 1)),
  ("日経下落 + 同時7+", (edf["nkRet1d"] < -1) & (edf["nHits"] >= 7)),
  ("前5日下落 + 出来高少", (edf["mom5"] < -1) & (edf["volRatio"] < 1)),
  ("前5日上昇 + 日経上昇", (edf["mom5"] > 1) & (edf["nkRet1d"] > 0.5)),
]

for name, mask in combos:
  n = mask.sum()
  if n < 10:
    continue
  fr = edf[mask]["filled"].mean() * 100
  diff = fr - baseFr
  marker = " <-- DANGER" if diff < -5 else (" <-- SAFE" if diff > 5 else "")
  print(f"  {name:>30s}  n={n:>4d}  fill={fr:>5.1f}%  {diff:>+6.1f}%{marker}")
