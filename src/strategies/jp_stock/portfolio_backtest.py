"""
日本小型株 ポートフォリオバックテスト

複数銘柄を横断スキャンし、シグナルが出た銘柄に投資する。
1日1銘柄のみ保有（少額資金前提）。
"""

import numpy as np
import pandas as pd

from strategies.jp_stock.backtest import calcFee
from strategies.jp_stock.screener import getPriceLimit


def _generateSignalsAll(stocksData: dict[str, pd.DataFrame],
                        strategy: str = "volume_breakout",
                        **params) -> pd.DataFrame:
  """
  全銘柄のシグナルを日付ごとに生成。

  Returns: DataFrame(date, symbol, signal_strength, price, volume, ...)
  """
  allSignals = []

  for sym, df in stocksData.items():
    if len(df) < 200:
      continue

    closes = df["close"].values
    volumes = df["volume"].values
    opens = df["open"].values
    highs = df["high"].values
    dates = df.index

    if strategy == "volume_breakout":
      volMultiple = params.get("volMultiple", 2.5)
      highPeriod = params.get("highPeriod", 20)

      for i in range(max(highPeriod, 25), len(df) - 1):
        avgVol20 = np.mean(volumes[i - 20:i])
        if avgVol20 == 0:
          continue
        volRatio = volumes[i] / avgVol20

        if volRatio < volMultiple:
          continue

        highMax = np.max(closes[i - highPeriod:i])
        if closes[i] < highMax:
          continue

        sma5 = np.mean(closes[i - 5:i])
        sma25 = np.mean(closes[i - 25:i])
        if closes[i] <= sma5 or closes[i] <= sma25:
          continue

        # シグナル強度 = 出来高倍率 + 高値更新幅
        highBreakPct = (closes[i] - highMax) / highMax * 100
        strength = volRatio * 10 + highBreakPct

        # RSIフィルター（過熱除外: RSI > 80はスキップ）
        if i >= 14:
          delta = np.diff(closes[i - 14:i + 1])
          gain = np.mean(np.maximum(delta, 0))
          loss = np.mean(np.maximum(-delta, 0))
          rsi = 100 - (100 / (1 + gain / max(loss, 1e-10)))
          if rsi > 80:
            continue
          # RSI 50-70が理想的
          if 50 <= rsi <= 70:
            strength += 10

        allSignals.append({
          "date": dates[i],
          "entryDate": dates[i + 1],
          "symbol": sym,
          "strength": strength,
          "price": closes[i],
          "nextOpen": opens[i + 1],
          "volRatio": volRatio,
        })

    elif strategy == "mean_reversion":
      rsiPeriod = params.get("rsiPeriod", 14)
      rsiOversold = params.get("rsiOversold", 30)
      minDropPct = params.get("minDropPct", 5)
      dropDays = params.get("dropDays", 5)

      for i in range(max(rsiPeriod + 1, dropDays + 1, 26), len(df) - 1):
        # RSI計算
        delta = np.diff(closes[i - rsiPeriod:i + 1])
        gain = np.mean(np.maximum(delta, 0))
        loss = np.mean(np.maximum(-delta, 0))
        rsi = 100 - (100 / (1 + gain / max(loss, 1e-10)))

        if rsi >= rsiOversold:
          continue

        # 直近N日の下落率
        dropPct = (closes[i] / np.max(closes[i - dropDays:i]) - 1) * 100
        if dropPct > -minDropPct:
          continue

        # SMA25の上にいた銘柄が一時的に下げたケース（トレンドは崩れていない）
        sma25 = np.mean(closes[i - 25:i])
        sma75 = np.mean(closes[i - 75:i]) if i >= 75 else sma25
        # 中長期トレンドが生きている（SMA75の上 or 近辺）
        if closes[i] < sma75 * 0.85:
          continue  # トレンド崩壊は除外

        # 出来高が枯れていないか（平均の0.5倍以上）
        avgVol20 = np.mean(volumes[i - 20:i])
        if avgVol20 == 0 or volumes[i] < avgVol20 * 0.5:
          continue

        # シグナル強度 = RSIが低いほど + 下落が大きいほど
        strength = (rsiOversold - rsi) * 2 + abs(dropPct)

        # 下ヒゲ確認（反転シグナル）
        if i > 0:
          bodySize = abs(closes[i] - opens[i])
          lowerWick = min(opens[i], closes[i]) - df["low"].values[i]
          if lowerWick > bodySize * 1.5:
            strength += 15  # 下ヒゲ長い = 反発の兆候

        allSignals.append({
          "date": dates[i],
          "entryDate": dates[i + 1],
          "symbol": sym,
          "strength": strength,
          "price": closes[i],
          "nextOpen": opens[i + 1],
          "volRatio": volumes[i] / avgVol20 if avgVol20 > 0 else 1,
        })

    elif strategy == "bb_squeeze":
      bbPeriod = params.get("bbPeriod", 20)
      bbStd = params.get("bbStd", 2.0)
      squeezePeriod = params.get("squeezePeriod", 60)
      squeezeThreshold = params.get("squeezeThreshold", 1.2)

      sma = pd.Series(closes).rolling(bbPeriod).mean().values
      std = pd.Series(closes).rolling(bbPeriod).std().values
      upper = sma + bbStd * std
      bw = (2 * bbStd * std) / np.where(sma > 0, sma, 1)

      startIdx = max(squeezePeriod + bbPeriod, 30)
      for i in range(startIdx, len(df) - 1):
        recentBW = np.mean(bw[i - 4:i + 1])
        minBW = np.nanmin(bw[i - squeezePeriod:i + 1])
        if np.isnan(recentBW) or np.isnan(minBW) or minBW == 0:
          continue

        if recentBW > minBW * squeezeThreshold:
          continue
        if np.isnan(upper[i]) or closes[i] <= upper[i]:
          continue

        avgVol10 = np.mean(volumes[i - 10:i])
        if avgVol10 == 0 or volumes[i] < avgVol10 * 1.5:
          continue

        # スクイーズ度合いが強いほど高スコア
        squeezeRatio = minBW / max(recentBW, 1e-10)
        strength = squeezeRatio * 50 + (closes[i] - upper[i]) / closes[i] * 100

        allSignals.append({
          "date": dates[i],
          "entryDate": dates[i + 1],
          "symbol": sym,
          "strength": strength,
          "price": closes[i],
          "nextOpen": opens[i + 1],
          "volRatio": volumes[i] / avgVol10 if avgVol10 > 0 else 1,
        })

  return pd.DataFrame(allSignals)


def runPortfolioBacktest(
  stocksData: dict[str, pd.DataFrame],
  strategy: str = "volume_breakout",
  initialCapital: float = 50_000,
  takeProfitPct: float = 8.0,
  stopLossPct: float = 4.0,
  maxHoldDays: int = 5,
  trailingStopPct: float = 3.0,
  slippagePct: float = 0.3,
  marketDf: pd.DataFrame = None,
  broker: str = "sbi",
  lotUnit: int = 1,
  **strategyParams,
) -> dict:
  """
  ポートフォリオバックテスト

  全銘柄を横断スキャンし、最もスコアの高い銘柄に投資。
  1銘柄ずつ保有（少額資金前提）。

  Returns: {"trades": list, "equity": Series, "metrics": dict}
  """
  # 全銘柄のシグナルを生成
  signalsDf = _generateSignalsAll(stocksData, strategy, **strategyParams)
  if signalsDf.empty:
    equity = pd.Series([initialCapital], index=[pd.Timestamp.now()])
    return {"trades": [], "equity": equity, "metrics": {}, "signalCount": 0}

  # 市場フィルター
  mktOk = None
  if marketDf is not None and len(marketDf) >= 200:
    mktClose = marketDf["close"].values
    mktDates = marketDf.index
    mktOk = {}
    for i in range(200, len(marketDf)):
      sma200 = np.mean(mktClose[i - 200:i])
      mktOk[mktDates[i].date()] = mktClose[i] > sma200

  # 日付順にソート
  signalsDf = signalsDf.sort_values("date")
  allDates = sorted(signalsDf["date"].unique())

  capital = initialCapital
  position = None  # {"symbol", "shares", "entryPrice", "entryDate", "peakPrice"}
  trades = []
  equityList = []

  for dt in allDates:
    # ポジション保有中 → エグジット判定
    if position is not None:
      sym = position["symbol"]
      if sym not in stocksData:
        continue
      df = stocksData[sym]
      # dtに対応する行を見つける
      mask = df.index <= dt
      if not mask.any():
        continue
      idx = df.index.get_indexer([dt], method="ffill")[0]
      if idx < 0:
        continue
      price = df["close"].values[idx]
      holdDays = (dt - position["entryDate"]).days

      if price > position["peakPrice"]:
        position["peakPrice"] = price

      pnlPct = (price - position["entryPrice"]) / position["entryPrice"] * 100
      peakDrop = (position["peakPrice"] - price) / position["peakPrice"] * 100

      slHit = pnlPct <= -stopLossPct
      tpHit = pnlPct >= takeProfitPct
      timeStop = holdDays >= maxHoldDays
      trailingHit = peakDrop >= trailingStopPct and holdDays >= 2

      if slHit or tpHit or timeStop or trailingHit:
        sellPrice = price * (1 - slippagePct / 100)
        proceeds = position["shares"] * sellPrice
        fee = calcFee(proceeds, broker=broker)
        capital += proceeds - fee
        pnlAmount = (proceeds - fee) - (position["shares"] * position["entryPrice"])

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
          "symbol": sym,
          "price": sellPrice, "fee": fee,
          "pnl": pnlAmount,
          "pnlPct": (sellPrice - position["entryPrice"]) / position["entryPrice"] * 100,
          "capitalAfter": capital,
          "holdDays": holdDays,
        })
        position = None

    # ポジションなし → 最良シグナルでエントリー
    if position is None:
      # 市場フィルター
      dtDate = dt.date() if hasattr(dt, "date") else dt
      if mktOk is not None and not mktOk.get(dtDate, True):
        equityList.append((dt, capital))
        continue

      daySignals = signalsDf[signalsDf["date"] == dt].sort_values("strength", ascending=False)
      for _, sig in daySignals.iterrows():
        buyPrice = sig["nextOpen"] * (1 + slippagePct / 100)
        investable = capital * 0.9
        fee = calcFee(investable, broker=broker)
        investable -= fee
        shares = int(investable / buyPrice)
        if shares < 1 or investable < buyPrice:
          continue

        # 単元株チェック（SBI S株=1株, 立花=100株）
        if lotUnit > 1:
          shares = (shares // lotUnit) * lotUnit
          if shares < lotUnit:
            continue

        actualCost = shares * buyPrice + fee
        capital -= actualCost

        position = {
          "symbol": sig["symbol"],
          "shares": shares,
          "entryPrice": buyPrice,
          "entryDate": dt,
          "peakPrice": buyPrice,
        }

        trades.append({
          "datetime": sig["entryDate"], "type": "buy", "reason": "signal",
          "symbol": sig["symbol"],
          "price": buyPrice, "fee": fee,
          "shares": shares,
          "strength": sig["strength"],
        })
        break  # 1銘柄のみ

    # 時価評価
    if position is not None:
      sym = position["symbol"]
      df = stocksData[sym]
      idx = df.index.get_indexer([dt], method="ffill")[0]
      if idx >= 0:
        val = capital + position["shares"] * df["close"].values[idx]
      else:
        val = capital
    else:
      val = capital
    equityList.append((dt, val))

  # 最終ポジション清算
  if position is not None:
    sym = position["symbol"]
    df = stocksData[sym]
    lastPrice = df["close"].values[-1] * (1 - slippagePct / 100)
    proceeds = position["shares"] * lastPrice
    fee = calcFee(proceeds)
    capital += proceeds - fee
    trades.append({
      "datetime": df.index[-1], "type": "sell", "reason": "end",
      "symbol": sym,
      "price": lastPrice, "fee": fee,
      "pnl": capital - initialCapital,
      "capitalAfter": capital,
    })
    equityList.append((df.index[-1], capital))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )

  # メトリクス
  sellTrades = [t for t in trades if t["type"] == "sell"]
  wins = [t for t in sellTrades if t.get("pnl", 0) > 0]
  totalTrades = len(sellTrades)
  finalValue = equity.iloc[-1] if len(equity) > 0 else initialCapital
  totalReturn = (finalValue - initialCapital) / initialCapital * 100

  peak = equity.cummax()
  dd = (equity - peak) / peak * 100
  mdd = dd.min() if len(dd) > 0 else 0

  grossProfit = sum(t["pnl"] for t in wins) if wins else 0
  grossLoss = abs(sum(t["pnl"] for t in sellTrades if t.get("pnl", 0) <= 0))
  pf = grossProfit / grossLoss if grossLoss > 0 else float("inf")

  metrics = {
    "initialCapital": initialCapital,
    "finalValue": finalValue,
    "totalReturn": totalReturn,
    "totalTrades": totalTrades,
    "winRate": len(wins) / totalTrades * 100 if totalTrades > 0 else 0,
    "profitFactor": pf,
    "mdd": mdd,
    "totalFees": sum(t.get("fee", 0) for t in trades),
    "signalCount": len(signalsDf),
    "uniqueStocks": signalsDf["symbol"].nunique(),
  }

  return {"trades": trades, "equity": equity, "metrics": metrics}


def runMomentumRankingBacktest(
  stocksData: dict[str, pd.DataFrame],
  initialCapital: float = 50_000,
  lookbackDays: int = 60,
  topN: int = 5,
  rebalanceDays: int = 20,
  slippagePct: float = 0.3,
  marketDf: pd.DataFrame = None,
  broker: str = "sbi",
) -> dict:
  """
  モメンタムランキング戦略バックテスト

  毎月（rebalanceDays日ごと）全銘柄をlookback日リターンでランキングし、
  上位topN銘柄に等金額分散投資する。S株なら1株単位で買える。

  - 市場トレンドが下落なら現金保有（全ポジション決済）
  - 銘柄ごとにSL-10%の損切りあり
  """
  # 共通の日付インデックスを作成
  allDates = set()
  for df in stocksData.values():
    allDates.update(df.index)
  allDates = sorted(allDates)

  if len(allDates) < lookbackDays + 50:
    return {"trades": [], "equity": pd.Series(dtype=float), "metrics": {}}

  # 市場フィルター（SMA50とSMA200の両方の上）
  mktBull = {}
  if marketDf is not None and len(marketDf) >= 200:
    mc = marketDf["close"]
    sma50 = mc.rolling(50).mean()
    sma200 = mc.rolling(200).mean()
    for dt in marketDf.index:
      s50 = sma50.get(dt)
      s200 = sma200.get(dt)
      if s50 is not None and s200 is not None and not (np.isnan(s50) or np.isnan(s200)):
        mktBull[dt.date()] = mc[dt] > s200

  capital = initialCapital
  positions = {}  # {symbol: {"shares": int, "entryPrice": float}}
  trades = []
  equityList = []
  lastRebalance = 0

  for dayIdx, dt in enumerate(allDates):
    dtDate = dt.date() if hasattr(dt, "date") else dt

    # 市場フィルター: 下落相場なら全決済して現金
    marketOk = mktBull.get(dtDate, True)

    if not marketOk and positions:
      for sym, pos in list(positions.items()):
        if sym not in stocksData:
          continue
        df = stocksData[sym]
        idx = df.index.get_indexer([dt], method="ffill")[0]
        if idx < 0:
          continue
        sellPrice = df["close"].values[idx] * (1 - slippagePct / 100)
        proceeds = pos["shares"] * sellPrice
        fee = calcFee(proceeds, broker=broker)
        capital += proceeds - fee
        pnl = (sellPrice - pos["entryPrice"]) * pos["shares"] - fee
        trades.append({
          "datetime": dt, "type": "sell", "reason": "market_filter",
          "symbol": sym, "price": sellPrice, "shares": pos["shares"],
          "fee": fee, "pnl": pnl, "capitalAfter": capital,
        })
      positions = {}

    # 個別銘柄SLチェック
    for sym, pos in list(positions.items()):
      if sym not in stocksData:
        continue
      df = stocksData[sym]
      idx = df.index.get_indexer([dt], method="ffill")[0]
      if idx < 0:
        continue
      price = df["close"].values[idx]
      pnlPct = (price - pos["entryPrice"]) / pos["entryPrice"] * 100
      if pnlPct <= -10:  # SL -10%
        sellPrice = price * (1 - slippagePct / 100)
        proceeds = pos["shares"] * sellPrice
        fee = calcFee(proceeds, broker=broker)
        capital += proceeds - fee
        pnl = (sellPrice - pos["entryPrice"]) * pos["shares"] - fee
        trades.append({
          "datetime": dt, "type": "sell", "reason": "stop_loss",
          "symbol": sym, "price": sellPrice, "shares": pos["shares"],
          "fee": fee, "pnl": pnl, "capitalAfter": capital,
        })
        del positions[sym]

    # リバランス判定
    if dayIdx - lastRebalance >= rebalanceDays and marketOk:
      lastRebalance = dayIdx

      # 全銘柄のモメンタム（lookback日リターン）を計算
      momentum = []
      for sym, df in stocksData.items():
        idx = df.index.get_indexer([dt], method="ffill")[0]
        if idx < lookbackDays:
          continue
        price = df["close"].values[idx]
        pastPrice = df["close"].values[idx - lookbackDays]
        if pastPrice <= 0 or price <= 0:
          continue

        ret = (price / pastPrice - 1) * 100

        # 出来高フィルター（直近20日平均3万株以上）
        vol20 = np.mean(df["volume"].values[max(0, idx - 20):idx])
        if vol20 < 30000:
          continue

        # 株価200円以上
        if price < 200:
          continue

        momentum.append({
          "symbol": sym,
          "return": ret,
          "price": price,
          "volume": vol20,
        })

      if not momentum:
        val = capital + sum(
          pos["shares"] * stocksData[sym]["close"].values[
            stocksData[sym].index.get_indexer([dt], method="ffill")[0]
          ] for sym, pos in positions.items()
          if sym in stocksData and stocksData[sym].index.get_indexer([dt], method="ffill")[0] >= 0
        )
        equityList.append((dt, val))
        continue

      # モメンタム上位N銘柄を選定
      momentum.sort(key=lambda x: x["return"], reverse=True)
      targets = [m["symbol"] for m in momentum[:topN]]

      # 現在保有でターゲット外の銘柄を売却
      for sym in list(positions.keys()):
        if sym not in targets:
          pos = positions[sym]
          df = stocksData[sym]
          idx = df.index.get_indexer([dt], method="ffill")[0]
          if idx < 0:
            continue
          sellPrice = df["close"].values[idx] * (1 - slippagePct / 100)
          proceeds = pos["shares"] * sellPrice
          fee = calcFee(proceeds, broker=broker)
          capital += proceeds - fee
          pnl = (sellPrice - pos["entryPrice"]) * pos["shares"] - fee
          trades.append({
            "datetime": dt, "type": "sell", "reason": "rebalance",
            "symbol": sym, "price": sellPrice, "shares": pos["shares"],
            "fee": fee, "pnl": pnl, "capitalAfter": capital,
          })
          del positions[sym]

      # ターゲット銘柄に等金額投資
      # まず総時価を計算
      totalVal = capital
      for sym, pos in positions.items():
        if sym in stocksData:
          df = stocksData[sym]
          idx = df.index.get_indexer([dt], method="ffill")[0]
          if idx >= 0:
            totalVal += pos["shares"] * df["close"].values[idx]

      targetAlloc = totalVal / topN  # 1銘柄あたりの目標金額

      for sym in targets:
        if sym in positions:
          continue  # 既に保有
        if sym not in stocksData:
          continue
        df = stocksData[sym]
        idx = df.index.get_indexer([dt], method="ffill")[0]
        if idx < 0:
          continue

        buyPrice = df["close"].values[idx] * (1 + slippagePct / 100)
        allocAmount = min(targetAlloc, capital * 0.95)
        fee = calcFee(allocAmount, broker=broker)
        investable = allocAmount - fee
        shares = int(investable / buyPrice)
        if shares < 1:
          continue

        actualCost = shares * buyPrice + fee
        if actualCost > capital:
          continue
        capital -= actualCost

        positions[sym] = {
          "shares": shares,
          "entryPrice": buyPrice,
        }
        trades.append({
          "datetime": dt, "type": "buy", "reason": "rebalance",
          "symbol": sym, "price": buyPrice, "shares": shares,
          "fee": fee,
        })

    # 時価評価
    val = capital
    for sym, pos in positions.items():
      if sym in stocksData:
        df = stocksData[sym]
        idx = df.index.get_indexer([dt], method="ffill")[0]
        if idx >= 0:
          val += pos["shares"] * df["close"].values[idx]
    equityList.append((dt, val))

  # 最終清算
  for sym, pos in positions.items():
    if sym not in stocksData:
      continue
    df = stocksData[sym]
    sellPrice = df["close"].values[-1] * (1 - slippagePct / 100)
    proceeds = pos["shares"] * sellPrice
    fee = calcFee(proceeds, broker=broker)
    capital += proceeds - fee
    pnl = (sellPrice - pos["entryPrice"]) * pos["shares"] - fee
    trades.append({
      "datetime": df.index[-1], "type": "sell", "reason": "end",
      "symbol": sym, "price": sellPrice, "shares": pos["shares"],
      "fee": fee, "pnl": pnl, "capitalAfter": capital,
    })
  positions = {}

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )

  # メトリクス
  sellTrades = [t for t in trades if t["type"] == "sell"]
  wins = [t for t in sellTrades if t.get("pnl", 0) > 0]
  totalTrades = len(sellTrades)
  finalValue = equity.iloc[-1] if len(equity) > 0 else initialCapital
  totalReturn = (finalValue - initialCapital) / initialCapital * 100

  peak = equity.cummax()
  dd = (equity - peak) / peak * 100
  mdd = dd.min() if len(dd) > 0 else 0

  grossProfit = sum(t["pnl"] for t in wins) if wins else 0
  grossLoss = abs(sum(t["pnl"] for t in sellTrades if t.get("pnl", 0) <= 0))
  pf = grossProfit / grossLoss if grossLoss > 0 else float("inf")

  return {
    "trades": trades,
    "equity": equity,
    "metrics": {
      "initialCapital": initialCapital,
      "finalValue": finalValue,
      "totalReturn": totalReturn,
      "totalTrades": totalTrades,
      "winRate": len(wins) / totalTrades * 100 if totalTrades > 0 else 0,
      "profitFactor": pf,
      "mdd": mdd,
      "totalFees": sum(t.get("fee", 0) for t in trades),
    },
  }


if __name__ == "__main__":
  import sys
  sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent / "src"))
  from strategies.jp_stock.data import fetchOhlcv, getSmallCapUniverse, fetchMultiple
  import random

  print("=== Portfolio Backtest ===\n")

  # 銘柄データ取得
  universe = getSmallCapUniverse()
  random.seed(42)
  sample = random.sample(universe, min(50, len(universe)))
  symbols = [s["symbol"] for s in sample]

  print(f"Fetching data for {len(symbols)} stocks...")
  stocksData = fetchMultiple(symbols, interval="1d", years=3)
  print(f"Got data for {len(stocksData)} stocks\n")

  # TOPIX
  try:
    marketDf = fetchOhlcv("^N225", interval="1d", years=3)
  except Exception:
    marketDf = None

  # バックテスト
  for strat in ["volume_breakout", "bb_squeeze"]:
    print(f"--- {strat} ---")
    result = runPortfolioBacktest(
      stocksData, strategy=strat,
      initialCapital=50_000, marketDf=marketDf,
    )
    m = result["metrics"]
    print(f"  Return: {m['totalReturn']:+.1f}%  Final: {m['finalValue']:,.0f}")
    print(f"  Trades: {m['totalTrades']}  WR: {m['winRate']:.1f}%  PF: {m['profitFactor']:.2f}")
    print(f"  MDD: {m['mdd']:.1f}%  Fees: {m['totalFees']:,.0f}")
    print(f"  Signals: {m['signalCount']}  Stocks: {m['uniqueStocks']}")
    print()
