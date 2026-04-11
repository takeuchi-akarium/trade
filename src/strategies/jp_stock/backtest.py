"""
日本小型株バックテストエンジン

手数料（固定+スリッページ）、値幅制限、タイムストップ、市場トレンドフィルター対応。
"""

import numpy as np
import pandas as pd

from strategies.jp_stock.screener import getPriceLimit


def _calcMarketFilter(marketDf: pd.DataFrame | None) -> np.ndarray | None:
  """
  市場トレンドフィルター: 日経225 (^N225) のSMA50/200で判定。
  price > SMA50 > SMA200 → True (エントリー可)
  それ以外 → False (エントリー不可)
  """
  if marketDf is None:
    return None
  close = marketDf["close"].values
  n = len(close)
  result = np.ones(n, dtype=bool)
  for i in range(200, n):
    sma50 = np.mean(close[i - 50:i])
    sma200 = np.mean(close[i - 200:i])
    # 上昇トレンドまたは中立 → OK
    result[i] = close[i] > sma200  # 最低限SMA200の上
  return result


# 立花証券 e支店 現物手数料テーブル（税込）
FEE_TABLE_TACHIBANA = [
  (50_000, 55),
  (100_000, 99),
  (200_000, 115),
  (500_000, 275),
  (1_000_000, 535),
  (1_500_000, 640),
  (30_000_000, 1_013),
]


def calcFee(tradeAmount: float, broker: str = "sbi") -> float:
  """
  約定代金から手数料を計算

  broker:
    "sbi" — SBI証券（1日100万円まで無料）
    "tachibana" — 立花証券 e支店
  """
  if broker == "sbi":
    return 0  # S株・現物ともに1日100万円まで無料
  for threshold, fee in FEE_TABLE_TACHIBANA:
    if tradeAmount <= threshold:
      return fee
  return 1_013


def runVolumeBreakoutBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  volMultiple: float = 2.5,
  highPeriod: int = 20,
  takeProfitPct: float = 8.0,
  stopLossPct: float = 4.0,
  maxHoldDays: int = 5,
  slippagePct: float = 0.3,
  trailingStopPct: float = 3.0,
  marketDf: pd.DataFrame = None,
) -> tuple[list[dict], pd.Series]:
  """
  出来高急増ブレイクアウト バックテスト

  エントリー: 出来高急増+高値更新+SMA上の翌日 + 市場トレンドOK
  エグジット: TP+8%, SL-4%, トレーリングストップ-3%, 5日タイムストップ
  """
  capital = initialCapital
  position = 0      # 保有株数
  entryPrice = 0.0
  entryIdx = 0      # エントリーした日のインデックス
  peakPrice = 0.0   # トレーリングストップ用の高値

  trades = []
  equityList = []

  closes = df["close"].values
  highs = df["high"].values
  volumes = df["volume"].values
  dates = df.index

  # 市場トレンドフィルター
  mktFilter = _calcMarketFilter(marketDf)

  for i in range(max(highPeriod, 25), len(df)):
    price = closes[i]
    dt = dates[i]

    # ポジション保有中
    if position > 0:
      holdDays = i - entryIdx
      pnlPct = (price - entryPrice) / entryPrice * 100

      # 高値更新（トレーリングストップ用）
      if price > peakPrice:
        peakPrice = price

      # 値幅制限チェック
      prevClose = closes[i - 1]
      limit = getPriceLimit(prevClose)
      effectivePrice = max(prevClose - limit, min(price, prevClose + limit))

      slHit = pnlPct <= -stopLossPct
      tpHit = pnlPct >= takeProfitPct
      timeStop = holdDays >= maxHoldDays
      # トレーリングストップ: 高値から-N%下落
      trailingHit = (peakPrice - price) / peakPrice * 100 >= trailingStopPct and holdDays >= 2

      if slHit or tpHit or timeStop or trailingHit:
        sellPrice = effectivePrice * (1 - slippagePct / 100)
        proceeds = position * sellPrice
        fee = calcFee(proceeds)
        capital += proceeds - fee
        pnlAmount = proceeds - fee - (position * entryPrice)

        if slHit:
          reason = "stop_loss"
        elif tpHit:
          reason = "take_profit"
        elif trailingHit:
          reason = "trailing_stop"
        else:
          reason = "time_stop"
        trades.append({
          "datetime": dt, "type": "sell", "reason": reason,
          "price": sellPrice, "fee": fee,
          "pnl": pnlAmount,
          "pnlPct": (sellPrice - entryPrice) / entryPrice * 100,
          "capitalAfter": capital,
          "holdDays": holdDays,
        })
        position = 0
        entryPrice = 0
        peakPrice = 0
        equityList.append((dt, capital))
        continue

    # シグナル判定（ポジションなしの場合）
    if position == 0:
      # 市場トレンドフィルター
      if mktFilter is not None and i < len(mktFilter) and not mktFilter[i]:
        equityList.append((dt, capital))
        continue

      # 出来高条件
      avgVol20 = np.mean(volumes[i - 20:i])
      volOk = volumes[i] >= avgVol20 * volMultiple

      # 高値更新条件
      highMax = np.max(closes[i - highPeriod:i])
      highOk = price >= highMax

      # トレンド条件（SMA5, SMA25の上）
      sma5 = np.mean(closes[i - 5:i])
      sma25 = np.mean(closes[i - 25:i])
      trendOk = price > sma5 and price > sma25

      if volOk and highOk and trendOk:
        # 翌日の始値でエントリー（スリッページ込み）
        if i + 1 < len(df):
          buyPrice = df["open"].values[i + 1] * (1 + slippagePct / 100)

          # 値幅制限チェック
          limit = getPriceLimit(price)
          if abs(buyPrice - price) > limit:
            equityList.append((dt, capital))
            continue

          # ポジションサイズ: 資金の90%
          investable = capital * 0.9
          fee = calcFee(investable)
          investable -= fee
          if investable < buyPrice:  # 最低1株買えるか
            equityList.append((dt, capital))
            continue

          position = int(investable / buyPrice)  # 株数は整数
          if position < 1:
            equityList.append((dt, capital))
            continue

          actualCost = position * buyPrice + fee
          capital -= actualCost
          entryPrice = buyPrice
          entryIdx = i + 1
          peakPrice = buyPrice

          trades.append({
            "datetime": dates[i + 1], "type": "buy", "reason": "signal",
            "price": buyPrice, "fee": fee,
            "shares": position,
            "signal_date": dt,
          })

    val = capital + (position * price if position > 0 else 0)
    equityList.append((dt, val))

  # 最終日にポジション残っていたら決済
  if position > 0:
    lastPrice = closes[-1] * (1 - slippagePct / 100)
    proceeds = position * lastPrice
    fee = calcFee(proceeds)
    capital += proceeds - fee
    trades.append({
      "datetime": dates[-1], "type": "sell", "reason": "end",
      "price": lastPrice, "fee": fee,
      "pnl": capital - initialCapital,
      "pnlPct": (lastPrice - entryPrice) / entryPrice * 100,
      "capitalAfter": capital,
    })
    equityList.append((dates[-1], capital))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity


def runBBSqueezeBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  bbPeriod: int = 20,
  bbStd: float = 2.0,
  squeezePeriod: int = 60,
  squeezeThreshold: float = 1.2,
  stopLossPct: float = 5.0,
  maxHoldDays: int = 10,
  slippagePct: float = 0.3,
  trailingStopPct: float = 3.0,
  marketDf: pd.DataFrame = None,
) -> tuple[list[dict], pd.Series]:
  """
  BBスクイーズブレイク バックテスト

  エントリー: スクイーズ状態 + 上バンド突破 + 出来高確認 + 市場トレンドOK
  エグジット: バンド内回帰 or SL-5% or トレーリングストップ or 10日タイムストップ
  """
  capital = initialCapital
  position = 0
  entryPrice = 0.0
  entryIdx = 0
  peakPrice = 0.0

  trades = []
  equityList = []

  close = df["close"]
  sma = close.rolling(bbPeriod).mean()
  std = close.rolling(bbPeriod).std()
  upper = sma + bbStd * std
  bandwidth = (2 * bbStd * std) / sma

  closes = close.values
  uppers = upper.values
  bws = bandwidth.values
  dates = df.index

  mktFilter = _calcMarketFilter(marketDf)
  startIdx = max(squeezePeriod + bbPeriod, 30)

  for i in range(startIdx, len(df)):
    price = closes[i]
    dt = dates[i]

    # ポジション保有中
    if position > 0:
      holdDays = i - entryIdx
      pnlPct = (price - entryPrice) / entryPrice * 100

      if price > peakPrice:
        peakPrice = price

      prevClose = closes[i - 1]
      limit = getPriceLimit(prevClose)

      slHit = pnlPct <= -stopLossPct
      timeStop = holdDays >= maxHoldDays
      bandReturn = price < uppers[i] and holdDays >= 2
      trailingHit = (peakPrice - price) / peakPrice * 100 >= trailingStopPct and holdDays >= 2

      if slHit or timeStop or bandReturn or trailingHit:
        sellPrice = price * (1 - slippagePct / 100)
        sellPrice = max(prevClose - limit, min(sellPrice, prevClose + limit))
        proceeds = position * sellPrice
        fee = calcFee(proceeds)
        capital += proceeds - fee
        pnlAmount = (proceeds - fee) - (position * entryPrice)

        if slHit:
          reason = "stop_loss"
        elif trailingHit:
          reason = "trailing_stop"
        elif timeStop:
          reason = "time_stop"
        else:
          reason = "band_return"
        trades.append({
          "datetime": dt, "type": "sell", "reason": reason,
          "price": sellPrice, "fee": fee,
          "pnl": pnlAmount,
          "pnlPct": (sellPrice - entryPrice) / entryPrice * 100,
          "capitalAfter": capital,
          "holdDays": holdDays,
        })
        position = 0
        entryPrice = 0
        peakPrice = 0
        equityList.append((dt, capital))
        continue

    # シグナル判定
    if position == 0:
      # 市場トレンドフィルター
      if mktFilter is not None and i < len(mktFilter) and not mktFilter[i]:
        equityList.append((dt, capital))
        continue

      # スクイーズ条件
      recentBW = np.mean(bws[i - 4:i + 1])
      minBW = np.nanmin(bws[i - squeezePeriod:i + 1])
      if np.isnan(recentBW) or np.isnan(minBW) or minBW == 0:
        equityList.append((dt, capital))
        continue
      squeezed = recentBW <= minBW * squeezeThreshold

      # 上バンド突破
      breakout = price > uppers[i] if not np.isnan(uppers[i]) else False

      # 出来高確認（10日平均の1.5倍）
      avgVol10 = np.mean(df["volume"].values[i - 10:i])
      volOk = df["volume"].values[i] >= avgVol10 * 1.5

      if squeezed and breakout and volOk:
        if i + 1 < len(df):
          buyPrice = df["open"].values[i + 1] * (1 + slippagePct / 100)

          limit = getPriceLimit(price)
          if abs(buyPrice - price) > limit:
            equityList.append((dt, capital))
            continue

          investable = capital * 0.9
          fee = calcFee(investable)
          investable -= fee
          if investable < buyPrice:
            equityList.append((dt, capital))
            continue

          position = int(investable / buyPrice)
          if position < 1:
            equityList.append((dt, capital))
            continue

          actualCost = position * buyPrice + fee
          capital -= actualCost
          entryPrice = buyPrice
          entryIdx = i + 1
          peakPrice = buyPrice

          trades.append({
            "datetime": dates[i + 1], "type": "buy", "reason": "signal",
            "price": buyPrice, "fee": fee,
            "shares": position,
          })

    val = capital + (position * price if position > 0 else 0)
    equityList.append((dt, val))

  # 最終日にポジション残っていたら決済
  if position > 0:
    lastPrice = closes[-1] * (1 - slippagePct / 100)
    proceeds = position * lastPrice
    fee = calcFee(proceeds)
    capital += proceeds - fee
    trades.append({
      "datetime": dates[-1], "type": "sell", "reason": "end",
      "price": lastPrice, "fee": fee,
      "pnl": capital - initialCapital,
      "pnlPct": (lastPrice - entryPrice) / entryPrice * 100,
      "capitalAfter": capital,
    })
    equityList.append((dates[-1], capital))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity
