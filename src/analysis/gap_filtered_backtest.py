"""ギャップ戦略: 事前情報フィルター付きバックテスト

フィルター:
  1. ATR: 高ボラ銘柄を優先（GDがATR範囲内なら埋まりやすい）
  2. 同時GD 8-14はスキップ（じわ売りゾーン）
  3. GDサイズ/ATR比でランキング（ATR対比で大きすぎるGDは避ける）
  4. ポジションサイズをGDサイズに応じて調整
"""
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

print("Loading...")
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

allDates = sorted(set().union(*[set(df.index) for df in allData.values()]))

# 銘柄ごとのATR（14日）をキャッシュ
def calcAtr(df, idx):
  """idx時点の14日ATR（%）"""
  if idx < 15:
    return 0
  h = df["high"].values
  l = df["low"].values
  c = df["close"].values
  trs = []
  for j in range(idx - 14, idx):
    tr = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    trs.append(tr)
  atr = np.mean(trs)
  return atr / c[idx - 1] * 100 if c[idx - 1] > 0 else 0


def calcVolTrend5(df, idx):
  """5日出来高トレンド（5日平均/20日平均）"""
  v = df["volume"].values
  if idx < 21:
    return 1.0
  vol5 = np.mean(v[max(0, idx - 5):idx])
  vol20 = np.mean(v[max(0, idx - 21):idx - 1])
  return vol5 / vol20 if vol20 > 0 else 1.0


def calcMom5(df, idx):
  """5日モメンタム（%）"""
  c = df["close"].values
  if idx < 6:
    return 0
  return (c[idx - 1] - c[idx - 6]) / c[idx - 6] * 100


def runBacktest(label, useSizeFilter=True, useJiwauriFilter=True,
                useAtrRank=True, useDynamicSize=True,
                maxPositionPct=0.95, minPositionPct=0.3,
                capital=50000, slPct=1.5, maxHold=3, slip=0.1):
  cash = capital
  pos = None
  trades = []
  eqList = []

  for dt in allDates:
    # --- エグジット ---
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
        trades.append({
          "dt": dt, "pnl": pnl, "reason": exitReason,
          "pnlPct": (sellP - pos["entry"]) / pos["entry"] * 100,
        })
        pos = None

    # --- エントリー ---
    if pos is None:
      candidates = []
      nHits = 0

      # 同時GD数カウント
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
        if gapPct <= -2.0:
          nHits += 1

      # じわ売りフィルター
      if useJiwauriFilter and 8 <= nHits <= 14:
        eqList.append((dt, cash))
        continue

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

        if gapPct > -2.0:
          continue

        atr = calcAtr(df, idx)
        mom5 = calcMom5(df, idx)
        volTrend5 = calcVolTrend5(df, idx)

        # ATRフィルター: 低ボラ銘柄はスキップ
        if useSizeFilter and atr < 1.5:
          continue

        # GD/ATR比: GDがATRの何倍か（大きすぎると異常）
        gdAtrRatio = abs(gapPct) / atr if atr > 0 else 99

        # スコア計算
        if useAtrRank:
          # ATR対比で「普通の範囲内」のGDを優先
          # gdAtrRatio=1.0（ATR 1つ分のGD）が最適
          # 大きすぎても小さすぎてもスコアが下がる
          sizeScore = 1.0 / (1.0 + abs(gdAtrRatio - 1.5))
          # ボーナス: mom5が負（既に下落中）
          momBonus = 1.2 if mom5 < -3 else (1.1 if mom5 < -1 else 1.0)
          # ボーナス: 出来高増加傾向
          volBonus = 1.2 if volTrend5 > 1.2 else 1.0
          score = sizeScore * momBonus * volBonus * atr
        else:
          score = abs(gapPct)

        candidates.append({
          "sym": sym, "gap": gapPct, "score": score,
          "open": todayOpen, "prevClose": prevClose,
          "atr": atr, "gdAtrRatio": gdAtrRatio,
        })

      if candidates:
        best = max(candidates, key=lambda x: x["score"])
        sym = best["sym"]
        buyP = best["open"] * (1 + slip / 100)

        # ポジションサイズ（GDサイズに応じて調整）
        if useDynamicSize:
          # GD/ATR比が大きいほどポジション小さく
          ratio = best["gdAtrRatio"]
          if ratio <= 1.0:
            sizePct = maxPositionPct
          elif ratio <= 2.0:
            sizePct = maxPositionPct * 0.7
          elif ratio <= 3.0:
            sizePct = maxPositionPct * 0.4
          else:
            sizePct = minPositionPct
        else:
          sizePct = maxPositionPct

        inv = cash * sizePct
        fee = calcFee(inv)
        shares = int((inv - fee) / buyP)
        if shares >= 1:
          cash -= shares * buyP + fee
          pos = {
            "sym": sym, "shares": shares, "entry": buyP,
            "target": best["prevClose"], "holdStart": dt,
          }

    val = cash
    if pos is not None:
      sym = pos["sym"]
      df = allData[sym]
      if dt in df.index:
        idx = df.index.get_loc(dt)
        p = df["close"].values[idx]
        val = cash + pos["shares"] * p
    eqList.append((dt, val))

  # 集計
  n = len(trades)
  wins = len([t for t in trades if t["pnl"] > 0])
  finalVal = eqList[-1][1] if eqList else capital
  ret = (finalVal - capital) / capital * 100
  wr = wins / n * 100 if n > 0 else 0

  eqArr = np.array([v for _, v in eqList])
  peak = np.maximum.accumulate(eqArr)
  dd = (eqArr - peak) / peak * 100
  mdd = dd.min()

  reasons = {}
  for t in trades:
    r = t["reason"]
    reasons[r] = reasons.get(r, 0) + 1

  pnls = [t["pnl"] for t in trades]
  wPnls = [p for p in pnls if p > 0]
  lPnls = [p for p in pnls if p <= 0]
  pf = abs(sum(wPnls) / sum(lPnls)) if lPnls and sum(lPnls) != 0 else 999

  # 最大連敗
  streak = 0
  maxStreak = 0
  for t in trades:
    if t["pnl"] <= 0:
      streak += 1
      maxStreak = max(maxStreak, streak)
    else:
      streak = 0

  # 月次
  eqS = pd.Series([v for _, v in eqList], index=pd.DatetimeIndex([d for d, _ in eqList]))
  monthly = eqS.resample("ME").last()
  mret = monthly.pct_change().dropna() * 100
  monthlyWR = (mret > 0).mean() * 100

  print(f"\n{'=' * 60}")
  print(f"{label}")
  print(f"{'=' * 60}")
  print(f"  trades: {n}  WR: {wr:.1f}%  PF: {pf:.2f}")
  print(f"  return: {ret:+.1f}%  final: {finalVal:,.0f}")
  print(f"  MDD: {mdd:.1f}%  max streak: {maxStreak}")
  print(f"  monthly: mean={mret.mean():+.2f}% WR={monthlyWR:.0f}%")
  print(f"  reasons: {reasons}")

  # 年別
  prev = capital
  for yr in sorted(set(d.year for d, _ in eqList)):
    yrEq = [(d, v) for d, v in eqList if d.year == yr]
    end = yrEq[-1][1]
    yrRet = (end - prev) / prev * 100
    print(f"    {yr}: {prev:>10,.0f} -> {end:>10,.0f} ({yrRet:+.1f}%)")
    prev = end

  return trades, eqList


# === テスト ===
print("\n--- Baseline: フィルターなし（元の戦略）---")
runBacktest("Baseline (no filter, gap largest, 95% size)",
            useSizeFilter=False, useJiwauriFilter=False,
            useAtrRank=False, useDynamicSize=False)

print("\n--- Filter 1: じわ売りスキップのみ ---")
runBacktest("Filter 1: skip 8-14 simultaneous GD",
            useSizeFilter=False, useJiwauriFilter=True,
            useAtrRank=False, useDynamicSize=False)

print("\n--- Filter 2: ATRランキング ---")
runBacktest("Filter 2: ATR-based ranking + low vol skip",
            useSizeFilter=True, useJiwauriFilter=False,
            useAtrRank=True, useDynamicSize=False)

print("\n--- Filter 3: 動的ポジションサイズ ---")
runBacktest("Filter 3: dynamic position sizing by GD/ATR",
            useSizeFilter=False, useJiwauriFilter=False,
            useAtrRank=False, useDynamicSize=True)

print("\n--- Filter ALL: 全フィルター ---")
runBacktest("ALL filters combined",
            useSizeFilter=True, useJiwauriFilter=True,
            useAtrRank=True, useDynamicSize=True)

print("\n--- Filter ALL + conservative size ---")
runBacktest("ALL filters + max 60% position",
            useSizeFilter=True, useJiwauriFilter=True,
            useAtrRank=True, useDynamicSize=True,
            maxPositionPct=0.6, minPositionPct=0.2)
