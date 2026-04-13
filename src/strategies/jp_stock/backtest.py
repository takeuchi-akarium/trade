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


def runGapFillBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  gapThreshold: float = 1.5,
  stopLossPct: float = 2.0,
  maxHoldDays: int = 3,
  slippagePct: float = 0.1,
  exitAtClose: bool = True,
  volFilter: float = 0.8,
  marketDf: pd.DataFrame = None,
) -> tuple[list[dict], pd.Series]:
  """
  ギャップフィル（窓埋め）バックテスト

  エントリー: 前日終値に対して-gapThreshold%以上のGD → 始値で買い
  エグジット:
    - exitAtClose=True: 当日引けで必ず決済（デイトレ）
    - exitAtClose=False: 窓埋め(high>=prevClose)で利確、SL or maxHoldDaysで損切り
  フィルター:
    - 出来高が20日平均のvolFilter倍以上（薄い日は避ける）
    - 市場トレンドフィルター（オプション）
  """
  capital = initialCapital
  position = 0
  entryPrice = 0.0
  entryIdx = 0
  targetPrice = 0.0

  trades = []
  equityList = []

  opens = df["open"].values
  highs = df["high"].values
  lows = df["low"].values
  closes = df["close"].values
  volumes = df["volume"].values
  dates = df.index

  mktFilter = _calcMarketFilter(marketDf)

  for i in range(25, len(df)):
    price = closes[i]
    dt = dates[i]

    # ポジション保有中（exitAtClose=Falseの場合のみ複数日保有）
    if position > 0 and not exitAtClose:
      holdDays = i - entryIdx

      gapFilled = highs[i] >= targetPrice
      slHit = lows[i] <= entryPrice * (1 - stopLossPct / 100)
      timeStop = holdDays >= maxHoldDays

      if gapFilled or slHit or timeStop:
        if slHit:
          sellPrice = entryPrice * (1 - stopLossPct / 100)
          reason = "stop_loss"
        elif gapFilled:
          sellPrice = targetPrice
          reason = "gap_fill"
        else:
          sellPrice = price
          reason = "time_stop"

        sellPrice *= (1 - slippagePct / 100)
        prevC = closes[i - 1]
        lim = getPriceLimit(prevC)
        sellPrice = max(prevC - lim, min(sellPrice, prevC + lim))

        proceeds = position * sellPrice
        fee = calcFee(proceeds)
        capital += proceeds - fee
        pnlAmount = (proceeds - fee) - (position * entryPrice)

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
        targetPrice = 0
        equityList.append((dt, capital))
        continue

    if position == 0:
      if mktFilter is not None and i < len(mktFilter) and not mktFilter[i]:
        equityList.append((dt, capital))
        continue

      prevClose = closes[i - 1]
      todayOpen = opens[i]

      if prevClose <= 0:
        equityList.append((dt, capital))
        continue
      gapPct = (todayOpen - prevClose) / prevClose * 100

      if gapPct <= -gapThreshold:
        avgVol20 = np.mean(volumes[max(0, i - 21):i - 1]) if i > 1 else 0
        if avgVol20 > 0 and volumes[i - 1] >= avgVol20 * volFilter:
          buyPrice = todayOpen * (1 + slippagePct / 100)

          lim = getPriceLimit(prevClose)
          if abs(buyPrice - prevClose) > lim:
            equityList.append((dt, capital))
            continue

          investable = capital * 0.95
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
          entryIdx = i
          targetPrice = prevClose

          trades.append({
            "datetime": dt, "type": "buy", "reason": "gap_down",
            "price": buyPrice, "fee": fee,
            "shares": position,
            "gapPct": gapPct,
          })

          if exitAtClose:
            gapFilled = highs[i] >= prevClose
            if gapFilled:
              sellPrice = prevClose * (1 - slippagePct / 100)
              reason = "gap_fill"
            elif lows[i] <= entryPrice * (1 - stopLossPct / 100):
              sellPrice = entryPrice * (1 - stopLossPct / 100)
              reason = "stop_loss"
            else:
              sellPrice = price * (1 - slippagePct / 100)
              reason = "close_exit"

            lim = getPriceLimit(prevClose)
            sellPrice = max(prevClose - lim, min(sellPrice, prevClose + lim))
            proceeds = position * sellPrice
            fee2 = calcFee(proceeds)
            capital += proceeds - fee2
            pnlAmount = (proceeds - fee2) - (position * entryPrice)

            trades.append({
              "datetime": dt, "type": "sell", "reason": reason,
              "price": sellPrice, "fee": fee2,
              "pnl": pnlAmount,
              "pnlPct": (sellPrice - entryPrice) / entryPrice * 100,
              "capitalAfter": capital,
              "holdDays": 0,
            })
            position = 0
            entryPrice = 0
            targetPrice = 0

    val = capital + (position * price if position > 0 else 0)
    equityList.append((dt, val))

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

  eqGap = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, eqGap


def _getRegimeAtIndex(marketDf: pd.DataFrame, targetDate) -> str:
  """
  指定日時点の市場レジームを返す。

  close > sma50 > sma200 → "uptrend"
  close < sma50 < sma200 → "downtrend"
  それ以外               → "range"
  """
  # targetDate以前のデータを絞り込む
  sub = marketDf[marketDf.index <= targetDate]
  if len(sub) < 200:
    return "range"

  closes = sub["close"].values
  n = len(closes)
  sma50 = np.mean(closes[n - 50:n])
  sma200 = np.mean(closes[n - 200:n])
  price = closes[-1]

  if price > sma50 > sma200:
    return "uptrend"
  if price < sma50 < sma200:
    return "downtrend"
  return "range"


def _calcAtr(df: pd.DataFrame, idx: int) -> float:
  """idx時点の14日ATR（%）。事前情報のみ使用。"""
  if idx < 15:
    return 0
  h = df["high"].values
  l = df["low"].values
  c = df["close"].values
  trs = []
  for j in range(idx - 14, idx):
    tr = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    trs.append(tr)
  return np.mean(trs) / c[idx - 1] * 100 if c[idx - 1] > 0 else 0


def runAdaptiveGapBacktest(
  df: pd.DataFrame,
  initialCapital: float = 50_000,
  gdThreshold: float = 1.5,
  guFollowRange: list = None,
  guFadeThreshold: float = 5.0,
  stopLossPct: float = 1.5,
  maxHoldDays: int = 3,
  slippagePct: float = 0.1,
  skipLargeGdInUptrend: bool = True,
  marketDf: pd.DataFrame = None,
  minAtr: float = 1.5,
  skipJiwauriRange: tuple = (8, 14),
  useAtrRank: bool = True,
  useDynamicSize: bool = True,
  maxPositionPct: float = 0.7,
  minPositionPct: float = 0.3,
) -> tuple[list[dict], pd.Series]:
  """
  適応型ギャップトレード バックテスト

  エントリールール（バックテスト結果に基づく統合ルール）:
    GD（gap <= -gdThreshold）      → 買い（GapFill）
      ただしGD5%+かつuptrendはスキップ（暴落初動の可能性）
    GU 3-5% かつ downtrend        → 買い（Follow）、TP 3%
    GU guFadeThreshold%+          → 空売り（Fade）、窓埋めで利確

  エグジット:
    GapFill/Fade: 窓埋め（high/lowがprevCloseに到達）で利確
    Follow: TP 3%で利確
    全共通: SL stopLossPct%, maxHold maxHoldDays日
  """
  if guFollowRange is None:
    guFollowRange = [3.0, 5.0]

  capital = initialCapital
  position = 0       # +N=ロング株数, -N=ショート株数（絶対値）
  entryPrice = 0.0
  entryIdx = 0
  targetPrice = 0.0  # GapFill/Fade の目標価格
  tradeType = ""     # "gap_fill" / "follow" / "fade"

  trades = []
  equityList = []

  opens = df["open"].values
  highs = df["high"].values
  lows = df["low"].values
  closes = df["close"].values
  dates = df.index

  for i in range(25, len(df)):
    price = closes[i]
    dt = dates[i]
    prevClose = closes[i - 1]

    # ── ポジション保有中 ──────────────────────────────
    if position != 0:
      holdDays = i - entryIdx
      isLong = position > 0
      shares = abs(position)

      if isLong:
        pnlPct = (price - entryPrice) / entryPrice * 100
        gapFilled = highs[i] >= targetPrice  # prevCloseまで上昇
        slHit = lows[i] <= entryPrice * (1 - stopLossPct / 100)
        tpHit = tradeType == "follow" and pnlPct >= 3.0
      else:
        # ショート: 価格が下がると利益
        pnlPct = (entryPrice - price) / entryPrice * 100
        gapFilled = lows[i] <= targetPrice   # prevCloseまで下落
        slHit = highs[i] >= entryPrice * (1 + stopLossPct / 100)
        tpHit = False  # Fadeは窓埋めのみ

      timeStop = holdDays >= maxHoldDays
      exitNeeded = gapFilled or slHit or tpHit or timeStop

      if exitNeeded:
        prevC = closes[i - 1]
        lim = getPriceLimit(prevC)

        if slHit:
          if isLong:
            rawExit = entryPrice * (1 - stopLossPct / 100)
          else:
            rawExit = entryPrice * (1 + stopLossPct / 100)
          reason = "stop_loss"
        elif gapFilled:
          rawExit = targetPrice
          reason = tradeType  # "gap_fill" / "fade"
        elif tpHit:
          rawExit = price
          reason = "follow"
        else:
          rawExit = price
          reason = "time_stop"

        # 値幅制限 + スリッページ
        rawExit = max(prevC - lim, min(rawExit, prevC + lim))
        if isLong:
          exitPrice = rawExit * (1 - slippagePct / 100)
          proceeds = shares * exitPrice
          fee = calcFee(proceeds)
          capital += proceeds - fee
          pnlAmount = (proceeds - fee) - (shares * entryPrice)
        else:
          # ショートの場合: 買い戻し
          exitPrice = rawExit * (1 + slippagePct / 100)
          cost = shares * exitPrice
          fee = calcFee(cost)
          pnlAmount = shares * (entryPrice - exitPrice) - fee
          capital += pnlAmount

        trades.append({
          "datetime": dt,
          "type": "sell" if isLong else "cover",
          "reason": reason,
          "price": exitPrice,
          "fee": fee,
          "pnl": pnlAmount,
          "pnlPct": (exitPrice - entryPrice) / entryPrice * 100 * (1 if isLong else -1),
          "capitalAfter": capital,
          "holdDays": holdDays,
          "gapPct": None,
          "regime": None,
        })
        position = 0
        entryPrice = 0.0
        targetPrice = 0.0
        tradeType = ""
        equityList.append((dt, capital))
        continue

    # ── エントリー判定（ポジションなし） ────────────────
    if position == 0:
      if prevClose <= 0:
        equityList.append((dt, capital))
        continue

      gapPct = (opens[i] - prevClose) / prevClose * 100

      # レジーム判定（marketDfがある場合のみ）
      regime = "range"
      if marketDf is not None:
        regime = _getRegimeAtIndex(marketDf, dt)

      doEntry = False
      entryDir = ""    # "long" / "short"
      entryReason = "" # "gap_fill" / "follow" / "fade"
      atr = 0.0        # GDフィルター通過後のATR値（動的サイズで再利用）

      # GD → 買い（GapFill）
      if gapPct <= -gdThreshold:
        # GD5%+かつuptrendはスキップ
        if skipLargeGdInUptrend and gapPct <= -5.0 and regime == "uptrend":
          pass
        else:
          # ATRフィルター: 低ボラ銘柄はスキップ
          atr = _calcAtr(df, i)
          if atr < minAtr:
            equityList.append((dt, capital))
            continue

          # じわ売りフィルター: 市場の緩やかな下落日はスキップ
          # (marketDfの当日リターンが-1〜-3%の範囲 = じわ売りに対応)
          if marketDf is not None:
            mktSub = marketDf[marketDf.index <= dt]
            if len(mktSub) >= 2:
              mktClose = mktSub["close"].values
              mktRet = (mktClose[-1] - mktClose[-2]) / mktClose[-2] * 100
              # skipJiwauriRange=(8,14) → 市場リターンが-0.8〜-1.4%の範囲をじわ売り日とみなす
              jiwauriLow = -skipJiwauriRange[1] * 0.1
              jiwauriHigh = -skipJiwauriRange[0] * 0.1
              if jiwauriLow <= mktRet <= jiwauriHigh:
                equityList.append((dt, capital))
                continue

          doEntry = True
          entryDir = "long"
          entryReason = "gap_fill"
          # ATRベーススコア（ランキング用。単銘柄バックテストでは参考値のみ）
          if useAtrRank and atr > 0:
            gdAtrRatio = abs(gapPct) / atr
            sizeScore = 1.0 / (1.0 + abs(gdAtrRatio - 1.5))
            mom5 = (closes[i - 1] - closes[max(0, i - 6)]) / closes[max(0, i - 6)] * 100 if closes[max(0, i - 6)] > 0 else 0
            momBonus = 1.2 if mom5 < -3 else (1.1 if mom5 < -1 else 1.0)
            _entryScore = sizeScore * momBonus * atr  # noqa: F841（将来のランキング用）
          else:
            gdAtrRatio = abs(gapPct) / atr if atr > 0 else 1.0
            _entryScore = abs(gapPct)  # noqa: F841

      # GU 3-5% かつ downtrend → 買い（Follow）
      elif guFollowRange[0] <= gapPct < guFollowRange[1] and regime == "downtrend":
        doEntry = True
        entryDir = "long"
        entryReason = "follow"

      # GU 5%+ → 空売り（Fade）
      elif gapPct >= guFadeThreshold:
        doEntry = True
        entryDir = "short"
        entryReason = "fade"

      if doEntry:
        todayOpen = opens[i]
        lim = getPriceLimit(prevClose)

        # 値幅制限: ギャップが大きすぎる場合はスキップ
        if abs(todayOpen - prevClose) > lim:
          equityList.append((dt, capital))
          continue

        # ポジションサイズ: GD（gap_fill）は動的調整、それ以外は95%固定
        if entryReason == "gap_fill" and useDynamicSize:
          # atrはGDフィルター通過済みなのでそのまま再利用（0の場合のみ再計算）
          atrForSize = atr if atr > 0 else _calcAtr(df, i)
          if atrForSize > 0:
            gdAtrRatioForSize = abs(gapPct) / atrForSize
            if gdAtrRatioForSize <= 1.0:
              sizePct = maxPositionPct
            elif gdAtrRatioForSize <= 2.0:
              sizePct = maxPositionPct * 0.7
            elif gdAtrRatioForSize <= 3.0:
              sizePct = maxPositionPct * 0.4
            else:
              sizePct = minPositionPct
          else:
            sizePct = maxPositionPct
          investable = capital * sizePct
        else:
          investable = capital * 0.95
        fee = calcFee(investable)
        investable -= fee

        if entryDir == "long":
          buyPrice = todayOpen * (1 + slippagePct / 100)
          if investable < buyPrice:
            equityList.append((dt, capital))
            continue
          shares = int(investable / buyPrice)
          if shares < 1:
            equityList.append((dt, capital))
            continue
          actualCost = shares * buyPrice + fee
          capital -= actualCost
          entryPrice = buyPrice
          position = shares
          targetPrice = prevClose   # GapFill目標 = 前日終値
          tradeType = entryReason

          trades.append({
            "datetime": dt,
            "type": "buy",
            "reason": entryReason,
            "price": buyPrice,
            "fee": fee,
            "shares": shares,
            "gapPct": gapPct,
            "regime": regime,
          })

        else:  # short
          sellPrice = todayOpen * (1 - slippagePct / 100)
          if investable < sellPrice:
            equityList.append((dt, capital))
            continue
          shares = int(investable / sellPrice)
          if shares < 1:
            equityList.append((dt, capital))
            continue
          # ショートエントリー: 証拠金として資金を確保（簡略化: 売り代金は後で受け取る想定）
          fee = calcFee(shares * sellPrice)
          capital -= fee
          entryPrice = sellPrice
          position = -shares
          targetPrice = prevClose   # Fade目標 = 前日終値（下落して窓埋め）
          tradeType = "fade"

          trades.append({
            "datetime": dt,
            "type": "short",
            "reason": "fade",
            "price": sellPrice,
            "fee": fee,
            "shares": shares,
            "gapPct": gapPct,
            "regime": regime,
          })

        entryIdx = i

    # 時価評価
    if position > 0:
      val = capital + position * price
    elif position < 0:
      # ショート: 含み損益 = (entryPrice - price) * shares
      val = capital + abs(position) * entryPrice + abs(position) * (entryPrice - price)
    else:
      val = capital
    equityList.append((dt, val))

  # ── 最終日決済 ───────────────────────────────────
  if position != 0:
    isLong = position > 0
    shares = abs(position)
    lastClose = closes[-1]
    prevC = closes[-2] if len(closes) >= 2 else lastClose
    lim = getPriceLimit(prevC)

    if isLong:
      rawExit = max(prevC - lim, min(lastClose, prevC + lim))
      exitPrice = rawExit * (1 - slippagePct / 100)
      proceeds = shares * exitPrice
      fee = calcFee(proceeds)
      capital += proceeds - fee
      pnlAmount = (proceeds - fee) - (shares * entryPrice)
    else:
      rawExit = max(prevC - lim, min(lastClose, prevC + lim))
      exitPrice = rawExit * (1 + slippagePct / 100)
      cost = shares * exitPrice
      fee = calcFee(cost)
      pnlAmount = shares * (entryPrice - exitPrice) - fee
      capital += pnlAmount

    trades.append({
      "datetime": dates[-1],
      "type": "sell" if isLong else "cover",
      "reason": "end",
      "price": exitPrice,
      "fee": fee,
      "pnl": pnlAmount,
      "pnlPct": (exitPrice - entryPrice) / entryPrice * 100 * (1 if isLong else -1),
      "capitalAfter": capital,
      "holdDays": len(df) - 1 - entryIdx,
      "gapPct": None,
      "regime": None,
    })
    equityList.append((dates[-1], capital))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity
