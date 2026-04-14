"""
短期売買バックテストエンジン

手数料・SL/TP対応。短期/長期の勝率メトリクスを算出。
Plotlyチャート出力。
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


# ---------------------------------------------------------------------------
# バックテスト実行
# ---------------------------------------------------------------------------

def runBacktest(
  df: pd.DataFrame,
  initialCapital: float = 100_000,
  feePct: float = 0.1,
  stopLossPct: float | None = None,
  takeProfitPct: float | None = None,
) -> tuple[list[dict], pd.Series]:
  """
  シグナル付きdfでバックテスト実行。

  シグナルは前足で発生し、翌足の始値(open)で約定する。
  SL/TPは日中の安値(low)/高値(high)で判定する。

  Returns:
    trades: 取引履歴リスト
    equity: 時系列の資産額Series
  """
  capital = initialCapital
  holding = 0.0
  entryPrice = 0.0
  feeRate = feePct / 100

  trades = []
  equityList = []
  pendingSignal = 0  # 前足のシグナルを保持

  for dt, row in df.iterrows():
    price = row["close"]
    execPrice = row["open"]  # 約定は始値
    low = row.get("low", price)
    high = row.get("high", price)

    # SL/TP判定（ポジション保有中、日中の安値/高値で判定）
    if holding > 0:
      # SL: 日中安値で判定
      slPnlPct = (low - entryPrice) / entryPrice * 100
      slHit = stopLossPct is not None and slPnlPct <= -stopLossPct
      # TP: 日中高値で判定
      tpPnlPct = (high - entryPrice) / entryPrice * 100
      tpHit = takeProfitPct is not None and tpPnlPct >= takeProfitPct

      if slHit or tpHit:
        # SL/TP発動時はSL/TPラインの価格で約定（スリッページなし近似）
        if slHit:
          exitPrice = entryPrice * (1 - stopLossPct / 100)
          reason = "stop_loss"
        else:
          exitPrice = entryPrice * (1 + takeProfitPct / 100)
          reason = "take_profit"
        proceeds = holding * exitPrice
        fee = proceeds * feeRate
        capital = proceeds - fee
        pnlPct = (exitPrice - entryPrice) / entryPrice * 100
        trades.append({
          "datetime": dt, "type": "sell", "reason": reason,
          "price": exitPrice, "fee": fee,
          "pnl": exitPrice - entryPrice,
          "pnlPct": pnlPct,
          "capitalAfter": capital,
        })
        holding = 0
        entryPrice = 0
        pendingSignal = 0  # SL/TP発動時はペンディングシグナルをクリア
        equityList.append((dt, capital))
        continue

    # 前足のシグナルを今足の始値で約定
    # 売りシグナル（ポジション決済）
    if pendingSignal == -1 and holding > 0:
      proceeds = holding * execPrice
      fee = proceeds * feeRate
      capital = proceeds - fee
      pnlPct = (execPrice - entryPrice) / entryPrice * 100
      trades.append({
        "datetime": dt, "type": "sell", "reason": "signal",
        "price": execPrice, "fee": fee,
        "pnl": execPrice - entryPrice,
        "pnlPct": pnlPct,
        "capitalAfter": capital,
      })
      holding = 0
      entryPrice = 0

    # 買いシグナル（新規エントリー）
    elif pendingSignal == 1 and holding == 0:
      fee = capital * feeRate
      investable = capital - fee
      holding = investable / execPrice
      entryPrice = execPrice
      trades.append({
        "datetime": dt, "type": "buy", "reason": "signal",
        "price": execPrice, "fee": fee,
        "holding": holding,
      })
      capital = 0

    # 今足のシグナルを次足用に保持
    pendingSignal = row.get("signal", 0)

    val = capital if holding == 0 else holding * price
    equityList.append((dt, val))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity


def runBacktestLongShort(
  df: pd.DataFrame,
  initialCapital: float = 100_000,
  feePct: float = 0.1,
  stopLossPct: float | None = None,
  takeProfitPct: float | None = None,
  dailyFeePct: float = 0.04,
) -> tuple[list[dict], pd.Series]:
  """
  ロング/ショート両対応バックテスト。

  signal=+1 → ロングエントリー（ショート保有中なら決済→���ング）
  signal=-1 → ショートエントリー（ロング保有中なら決済→ショート）
  signal= 0 → 何もしない

  シグナルは前足で発生し、翌足の始値(open)で約定する。
  SL/TPは日中の安値(low)/高値(high)で判定する。

  dailyFeePct: 建玉管理料（日次、レバレッジ取引のコスト）
  """
  capital = initialCapital
  position = 0      # +1=long, -1=short, 0=none
  size = 0.0
  entryPrice = 0.0
  feeRate = feePct / 100
  dailyFeeRate = dailyFeePct / 100

  trades = []
  equityList = []
  prevDt = None
  pendingSignal = 0  # 前足のシグナルを保持

  for dt, row in df.iterrows():
    price = row["close"]
    execPrice = row["open"]  # 約定は始値
    low = row.get("low", price)
    high = row.get("high", price)

    # 建玉管理料（日をまたいだら適用）
    if position != 0 and prevDt is not None:
      daysDiff = (dt - prevDt).total_seconds() / 86400
      if daysDiff >= 0.5:  # 半日以上で1日分
        mgmtFee = abs(size) * entryPrice * dailyFeeRate * max(1, int(daysDiff))
        capital -= mgmtFee

    # SL/TP判定（日中の安値/高値で判定）
    if position != 0:
      if position == 1:
        slPnlPct = (low - entryPrice) / entryPrice * 100
        tpPnlPct = (high - entryPrice) / entryPrice * 100
      else:
        slPnlPct = (entryPrice - high) / entryPrice * 100
        tpPnlPct = (entryPrice - low) / entryPrice * 100

      slHit = stopLossPct is not None and slPnlPct <= -stopLossPct
      tpHit = takeProfitPct is not None and tpPnlPct >= takeProfitPct

      if slHit or tpHit:
        # SL/TP発動時はライン価格で約定
        if slHit:
          if position == 1:
            exitPrice = entryPrice * (1 - stopLossPct / 100)
          else:
            exitPrice = entryPrice * (1 + stopLossPct / 100)
          reason = "stop_loss"
        else:
          if position == 1:
            exitPrice = entryPrice * (1 + takeProfitPct / 100)
          else:
            exitPrice = entryPrice * (1 - takeProfitPct / 100)
          reason = "take_profit"
        pnlAmount = size * (exitPrice - entryPrice) * position
        pnlPct = pnlAmount / (size * entryPrice) * 100
        fee = abs(size * exitPrice) * feeRate
        if position == 1:
          capital = size * exitPrice - fee
        else:
          capital += pnlAmount - fee
        trades.append({
          "datetime": dt, "type": "close",
          "side": "long" if position == 1 else "short",
          "reason": reason,
          "price": exitPrice, "fee": fee,
          "pnl": pnlAmount, "pnlPct": pnlPct,
          "capitalAfter": capital,
        })
        position = 0
        size = 0
        entryPrice = 0
        pendingSignal = 0
        equityList.append((dt, capital))
        prevDt = dt
        continue

    # 前足のシグナルを今足の始値で約定
    if pendingSignal == 1 and position != 1:
      # ショート保有中なら決済
      if position == -1:
        pnlAmount = size * (entryPrice - execPrice)
        fee = abs(size * execPrice) * feeRate
        capital += pnlAmount - fee
        pnlPct = (entryPrice - execPrice) / entryPrice * 100
        trades.append({
          "datetime": dt, "type": "close", "side": "short",
          "reason": "signal", "price": execPrice, "fee": fee,
          "pnl": pnlAmount, "pnlPct": pnlPct,
          "capitalAfter": capital,
        })
        position = 0
        size = 0

      # ロングエントリー
      fee = capital * feeRate
      investable = capital - fee
      size = investable / execPrice
      entryPrice = execPrice
      position = 1
      capital = 0
      trades.append({
        "datetime": dt, "type": "open", "side": "long",
        "reason": "signal", "price": execPrice, "fee": fee,
        "size": size,
      })

    elif pendingSignal == -1 and position != -1:
      # ロング保有中なら決済
      if position == 1:
        proceeds = size * execPrice
        fee = proceeds * feeRate
        pnlAmount = size * (execPrice - entryPrice)
        pnlPct = (execPrice - entryPrice) / entryPrice * 100
        capital = proceeds - fee
        trades.append({
          "datetime": dt, "type": "close", "side": "long",
          "reason": "signal", "price": execPrice, "fee": fee,
          "pnl": pnlAmount, "pnlPct": pnlPct,
          "capitalAfter": capital,
        })
        position = 0
        size = 0

      # ショートエントリー（現金を担保として保持、手数料差引）
      fee = capital * feeRate
      capital -= fee
      size = capital / execPrice
      entryPrice = execPrice
      position = -1
      trades.append({
        "datetime": dt, "type": "open", "side": "short",
        "reason": "signal", "price": execPrice, "fee": fee,
        "size": size,
      })

    # 今足のシグナルを次足用に保持
    pendingSignal = row.get("signal", 0)

    # 時価評価
    if position == 0:
      val = capital
    elif position == 1:
      val = size * price
    else:  # short
      val = capital + size * (entryPrice - price)
    equityList.append((dt, val))
    prevDt = dt

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity


# ---------------------------------------------------------------------------
# メトリクス
# ---------------------------------------------------------------------------

def calcMetrics(
  trades: list[dict],
  equity: pd.Series,
  initialCapital: float,
) -> dict:
  """全体 + 短期 + 長期の勝率メトリクスを算出"""
  sellTrades = [t for t in trades if t["type"] in ("sell", "close")]
  wins = [t for t in sellTrades if t["pnl"] > 0]
  losses = [t for t in sellTrades if t["pnl"] <= 0]
  nSells = len(sellTrades)

  finalValue = equity.iloc[-1] if len(equity) > 0 else initialCapital
  totalReturn = (finalValue - initialCapital) / initialCapital * 100

  # プロフィットファクター
  grossProfit = sum(t["pnl"] for t in wins) if wins else 0
  grossLoss = abs(sum(t["pnl"] for t in losses)) if losses else 1
  pf = grossProfit / grossLoss if grossLoss > 0 else float("inf")

  # MDD
  peak = equity.cummax()
  dd = (equity - peak) / peak * 100
  mdd = dd.min()

  # 手数料合計
  totalFees = sum(t.get("fee", 0) for t in trades)

  # --- 短期勝率（直近N件） ---
  def _recentWinRate(n):
    if nSells < n:
      return None
    recent = sellTrades[-n:]
    return len([t for t in recent if t["pnl"] > 0]) / n * 100

  # --- 長期勝率（月別） ---
  monthlyStats = _calcMonthlyStats(sellTrades)
  monthlyWinRates = [m["winRate"] for m in monthlyStats if m["trades"] > 0]
  winRateStability = np.std(monthlyWinRates) if len(monthlyWinRates) > 1 else 0

  return {
    # 全体
    "initialCapital": initialCapital,
    "finalValue": finalValue,
    "totalReturn": totalReturn,
    "totalTrades": nSells,
    "winRate": len(wins) / nSells * 100 if nSells else 0,
    "profitFactor": pf,
    "mdd": mdd,
    "totalFees": totalFees,
    # 短期勝率
    "winRate20": _recentWinRate(20),
    "winRate50": _recentWinRate(50),
    # 長期勝率
    "monthlyStats": monthlyStats,
    "winRateStability": winRateStability,
  }


def _calcMonthlyStats(sellTrades: list[dict]) -> list[dict]:
  """月別の勝率・損益を集計"""
  if not sellTrades:
    return []

  monthly = {}
  for t in sellTrades:
    key = t["datetime"].strftime("%Y-%m")
    if key not in monthly:
      monthly[key] = {"month": key, "wins": 0, "losses": 0, "pnl": 0}
    if t["pnl"] > 0:
      monthly[key]["wins"] += 1
    else:
      monthly[key]["losses"] += 1
    monthly[key]["pnl"] += t["pnl"]

  result = []
  for key in sorted(monthly.keys()):
    m = monthly[key]
    total = m["wins"] + m["losses"]
    result.append({
      "month": m["month"],
      "trades": total,
      "winRate": m["wins"] / total * 100 if total > 0 else 0,
      "pnl": m["pnl"],
    })
  return result


def calcRollingWinRate(trades: list[dict], window: int = 20) -> pd.DataFrame:
  """ローリング勝率を算出（短期勝率の推移可視化用）"""
  sellTrades = [t for t in trades if t["type"] in ("sell", "close")]
  if len(sellTrades) < window:
    return pd.DataFrame(columns=["datetime", "rollingWinRate"])

  results = []
  for i in range(window, len(sellTrades) + 1):
    batch = sellTrades[i - window:i]
    wr = len([t for t in batch if t["pnl"] > 0]) / window * 100
    results.append({"datetime": batch[-1]["datetime"], "rollingWinRate": wr})

  return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

def printMetrics(metrics: dict, strategyName: str) -> None:
  """メトリクスをターミナル表示"""
  print(f"\n{'=' * 60}")
  print(f"  {strategyName}")
  print(f"{'=' * 60}")

  print(f"\n【全体】")
  print(f"  初期資金      : {metrics['initialCapital']:>14,.0f}")
  print(f"  最終資産      : {metrics['finalValue']:>14,.0f}")
  print(f"  総リターン    : {metrics['totalReturn']:>13.2f}%")
  print(f"  トレード回数  : {metrics['totalTrades']:>14d}")
  print(f"  勝率          : {metrics['winRate']:>13.1f}%")
  print(f"  PF            : {metrics['profitFactor']:>14.2f}")
  print(f"  MDD           : {metrics['mdd']:>13.2f}%")
  print(f"  手数料合計    : {metrics['totalFees']:>14,.0f}")

  print(f"\n【短期勝率】")
  wr20 = metrics["winRate20"]
  wr50 = metrics["winRate50"]
  print(f"  直近20件      : {f'{wr20:.1f}%' if wr20 is not None else 'データ不足':>14s}")
  print(f"  直近50件      : {f'{wr50:.1f}%' if wr50 is not None else 'データ不足':>14s}")

  print(f"\n【長期勝率】")
  print(f"  全期間勝率    : {metrics['winRate']:>13.1f}%")
  print(f"  月別勝率σ     : {metrics['winRateStability']:>13.1f}%  (低いほど安定)")

  ms = metrics["monthlyStats"]
  if ms:
    print(f"\n【月別パフォーマンス】")
    print(f"  {'月':>7s}  {'取引数':>6s}  {'勝率':>7s}  {'損益':>12s}")
    print(f"  {'-' * 38}")
    for m in ms:
      print(f"  {m['month']:>7s}  {m['trades']:>6d}  {m['winRate']:>6.1f}%  {m['pnl']:>+12,.0f}")


# ---------------------------------------------------------------------------
# チャート
# ---------------------------------------------------------------------------

def plotResult(
  df: pd.DataFrame,
  trades: list[dict],
  equity: pd.Series,
  initialCapital: float,
  strategyName: str,
  symbol: str,
  interval: str,
  output: str | None = None,
) -> None:
  """Plotlyチャート出力: 価格+売買, 資産推移, ローリング勝率"""
  rollingWr = calcRollingWinRate(trades, window=20)
  hasRolling = len(rollingWr) > 0

  nRows = 3 if hasRolling else 2
  heights = [0.50, 0.25, 0.25] if hasRolling else [0.60, 0.40]
  subtitles = [
    f"{symbol} {interval}  {strategyName}",
    "資産推移 (%)",
  ]
  if hasRolling:
    subtitles.append("ローリング勝率 (直近20件)")

  fig = make_subplots(
    rows=nRows, cols=1,
    shared_xaxes=True,
    row_heights=heights,
    subplot_titles=subtitles,
    vertical_spacing=0.05,
  )

  # --- Row1: 価格 ---
  fig.add_trace(go.Candlestick(
    x=df.index, open=df["open"], high=df["high"],
    low=df["low"], close=df["close"],
    name=symbol,
    increasing_line_color="limegreen",
    decreasing_line_color="tomato",
  ), row=1, col=1)

  # 買いポイント
  buys = [t for t in trades if t["type"] == "buy"]
  if buys:
    fig.add_trace(go.Scatter(
      x=[t["datetime"] for t in buys],
      y=[t["price"] for t in buys],
      mode="markers", name="買い",
      marker=dict(symbol="triangle-up", size=12, color="limegreen",
                  line=dict(width=1, color="darkgreen")),
    ), row=1, col=1)

  # 売りポイント
  sells = [t for t in trades if t["type"] == "sell"]
  if sells:
    colors = {"signal": "red", "stop_loss": "orange", "take_profit": "cyan"}
    for reason, color in colors.items():
      pts = [t for t in sells if t.get("reason") == reason]
      if pts:
        label = {"signal": "売り", "stop_loss": "SL", "take_profit": "TP"}[reason]
        fig.add_trace(go.Scatter(
          x=[t["datetime"] for t in pts],
          y=[t["price"] for t in pts],
          mode="markers", name=label,
          marker=dict(symbol="triangle-down", size=12, color=color,
                      line=dict(width=1, color="dark" + color if color != "cyan" else "teal")),
        ), row=1, col=1)

  # --- Row2: 資産推移 ---
  equityPct = (equity / initialCapital - 1) * 100
  bnhPct = (df["close"] / df["close"].iloc[0] - 1) * 100

  fig.add_trace(go.Scatter(
    x=df.index, y=bnhPct, name="バイアンドホールド",
    line=dict(color="gray", width=1.2, dash="dash"),
  ), row=2, col=1)
  fig.add_trace(go.Scatter(
    x=equity.index, y=equityPct, name="戦略リターン",
    fill="tozeroy", line=dict(color="gold", width=1.5),
    fillcolor="rgba(255,215,0,0.1)",
  ), row=2, col=1)
  fig.add_hline(y=0, line=dict(color="white", width=0.5, dash="dot"), row=2, col=1)

  # --- Row3: ローリング勝率 ---
  if hasRolling:
    fig.add_trace(go.Scatter(
      x=rollingWr["datetime"], y=rollingWr["rollingWinRate"],
      name="勝率(20)", line=dict(color="violet", width=1.5),
      fill="tozeroy", fillcolor="rgba(238,130,238,0.1)",
    ), row=3, col=1)
    fig.add_hline(y=50, line=dict(color="white", width=0.5, dash="dot"), row=3, col=1)
    fig.update_yaxes(title_text="勝率 (%)", range=[0, 100], row=3, col=1)

  fig.update_layout(
    height=250 * nRows + 100,
    xaxis_rangeslider_visible=False,
    template="plotly_dark",
    hovermode="x unified",
  )
  fig.update_yaxes(title_text="Price", row=1, col=1)
  fig.update_yaxes(title_text="リターン (%)", row=2, col=1)

  if output is None:
    output = f"scalping_{symbol}_{interval}_{strategyName}.html"
  outPath = Path("data") / "scalping" / output
  outPath.parent.mkdir(parents=True, exist_ok=True)
  fig.write_html(str(outPath), auto_open=True)
  print(f"\nチャート保存: {outPath}")


# ---------------------------------------------------------------------------
# 比較チャート（1画面に全戦略）
# ---------------------------------------------------------------------------

STRATEGY_COLORS = {
  "rsi": "royalblue",
  "bb": "gold",
  "ema": "limegreen",
  "vwap": "violet",
}


def plotCompare(
  df: pd.DataFrame,
  results: list[dict],
  initialCapital: float,
  symbol: str,
  interval: str,
) -> None:
  """
  左半分にチャート、右半分に情報パネル。リターン率順にソート。
  Plotlyのsubplotsでは難しいのでHTML直書き。
  """
  from plotly.offline import get_plotlyjs

  # リターン降順ソート
  results = sorted(results, key=lambda r: r["metrics"]["totalReturn"], reverse=True)
  bnhPct = (df["close"] / df["close"].iloc[0] - 1) * 100

  cards = []
  for rank, r in enumerate(results):
    color = STRATEGY_COLORS.get(r["key"], "white")
    m = r["metrics"]

    # --- チャート（資産推移 + 勝率）---
    fig = make_subplots(
      rows=2, cols=1,
      shared_xaxes=True,
      row_heights=[0.65, 0.35],
      vertical_spacing=0.06,
    )

    eqPct = (r["equity"] / initialCapital - 1) * 100
    fig.add_trace(go.Scatter(
      x=df.index, y=bnhPct, name="BnH",
      line=dict(color="gray", width=1, dash="dash"),
      showlegend=(rank == 0),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
      x=r["equity"].index, y=eqPct,
      name=r["name"], line=dict(color=color, width=2),
      fill="tozeroy", fillcolor="rgba(255,255,255,0.03)",
    ), row=1, col=1)
    fig.add_hline(y=0, line=dict(color="white", width=0.3, dash="dot"), row=1, col=1)

    # 売買ポイント
    buys = [t for t in r["trades"] if t["type"] == "buy"]
    sells = [t for t in r["trades"] if t["type"] == "sell"]
    if buys:
      buyDts = [t["datetime"] for t in buys]
      buyVals = [eqPct.loc[dt] if dt in eqPct.index else 0 for dt in buyDts]
      fig.add_trace(go.Scatter(
        x=buyDts, y=buyVals, mode="markers", showlegend=False,
        marker=dict(symbol="triangle-up", size=8, color="limegreen",
                    line=dict(width=1, color="white")),
      ), row=1, col=1)
    if sells:
      sellDts = [t["datetime"] for t in sells]
      sellVals = [eqPct.loc[dt] if dt in eqPct.index else 0 for dt in sellDts]
      fig.add_trace(go.Scatter(
        x=sellDts, y=sellVals, mode="markers", showlegend=False,
        marker=dict(symbol="triangle-down", size=8, color="red",
                    line=dict(width=1, color="white")),
      ), row=1, col=1)

    fig.update_yaxes(title_text="%", row=1, col=1)

    # ローリング勝率
    rw = calcRollingWinRate(r["trades"], window=20)
    if len(rw) > 0:
      fig.add_trace(go.Scatter(
        x=rw["datetime"], y=rw["rollingWinRate"], showlegend=False,
        line=dict(color=color, width=1.5),
        fill="tozeroy", fillcolor="rgba(255,255,255,0.03)",
      ), row=2, col=1)
    fig.add_hline(y=50, line=dict(color="white", width=0.3, dash="dot"), row=2, col=1)
    fig.update_yaxes(title_text="勝率%", range=[0, 100], row=2, col=1)

    fig.update_layout(
      height=280, margin=dict(l=40, r=10, t=10, b=30),
      xaxis_rangeslider_visible=False,
      template="plotly_dark",
      showlegend=False,
      paper_bgcolor="rgba(0,0,0,0)",
      plot_bgcolor="rgba(20,20,30,1)",
    )

    chartDiv = f"chart_{rank}"
    chartJson = fig.to_json()

    # --- 情報パネル（HTML） ---
    wr20 = f"{m['winRate20']:.0f}%" if m["winRate20"] is not None else "-"
    wr50 = f"{m['winRate50']:.0f}%" if m["winRate50"] is not None else "-"

    # 月別勝率
    ms = m["monthlyStats"]
    monthlyRows = ""
    for mo in ms[-8:]:
      wrColor = "#4dff91" if mo["winRate"] >= 50 else "#ff5555"
      pnlColor = "#4dff91" if mo["pnl"] >= 0 else "#ff5555"
      monthlyRows += (
        f'<tr><td>{mo["month"]}</td><td>{mo["trades"]}</td>'
        f'<td style="color:{wrColor}">{mo["winRate"]:.0f}%</td>'
        f'<td style="color:{pnlColor}">{mo["pnl"]:+,.0f}</td></tr>'
      )

    retColor = "#4dff91" if m["totalReturn"] >= 0 else "#ff5555"

    infoHtml = f"""
    <div style="font-size:13px;color:#ccc;line-height:1.7">
      <div style="font-size:20px;font-weight:bold;color:{color};margin-bottom:8px">
        #{rank+1} {r['name']}
      </div>
      <div style="font-size:28px;font-weight:bold;color:{retColor};margin-bottom:12px">
        {m['totalReturn']:+.1f}%
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr><td style="color:#888">最終資産</td><td style="text-align:right">{m['finalValue']:,.0f}</td></tr>
        <tr><td style="color:#888">取引回数</td><td style="text-align:right">{m['totalTrades']}件</td></tr>
        <tr><td style="color:#888">勝率(全体)</td><td style="text-align:right">{m['winRate']:.1f}%</td></tr>
        <tr><td style="color:#888">PF</td><td style="text-align:right">{m['profitFactor']:.2f}</td></tr>
        <tr><td style="color:#888">MDD</td><td style="text-align:right;color:#ff5555">{m['mdd']:.1f}%</td></tr>
        <tr><td style="color:#888">手数料合計</td><td style="text-align:right">{m['totalFees']:,.0f}</td></tr>
      </table>
      <div style="margin-top:12px;padding-top:8px;border-top:1px solid #333">
        <div style="color:#888;font-size:11px;margin-bottom:4px">短期 vs 長期</div>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <tr><td style="color:#888">直近20件</td><td style="text-align:right">{wr20}</td></tr>
          <tr><td style="color:#888">直近50件</td><td style="text-align:right">{wr50}</td></tr>
          <tr><td style="color:#888">月別安定性(σ)</td><td style="text-align:right">{m['winRateStability']:.1f}%</td></tr>
        </table>
      </div>
      <div style="margin-top:12px;padding-top:8px;border-top:1px solid #333">
        <div style="color:#888;font-size:11px;margin-bottom:4px">月別パフォーマンス</div>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <tr style="color:#666"><td>月</td><td>件数</td><td>勝率</td><td>損益</td></tr>
          {monthlyRows}
        </table>
      </div>
    </div>
    """

    cards.append({
      "chartDiv": chartDiv,
      "chartJson": chartJson,
      "infoHtml": infoHtml,
    })

  # --- HTML組み立て ---
  cardSections = ""
  scriptInits = ""
  for c in cards:
    cardSections += f"""
    <div style="display:flex;gap:0;margin-bottom:2px;background:#0d0d14;border:1px solid #222;border-radius:6px;overflow:hidden">
      <div id="{c['chartDiv']}" style="flex:1;min-width:0"></div>
      <div style="width:280px;padding:16px 20px;border-left:1px solid #222;flex-shrink:0">
        {c['infoHtml']}
      </div>
    </div>
    """
    scriptInits += f"Plotly.newPlot('{c['chartDiv']}', ...JSON.parse('{{}}'.replace('{{}}',`{c['chartJson']}`)).data.map(function(t){{return t}}), JSON.parse(`{c['chartJson']}`).layout);\n"

  # Plotly.newPlotを安全に呼ぶ
  scriptParts = ""
  for c in cards:
    scriptParts += f"""
    (function() {{
      var spec = JSON.parse(document.getElementById('data-{c["chartDiv"]}').textContent);
      Plotly.newPlot('{c["chartDiv"]}', spec.data, spec.layout);
    }})();
    """

  dataScripts = ""
  for c in cards:
    dataScripts += f'<script id="data-{c["chartDiv"]}" type="application/json">{c["chartJson"]}</script>\n'

  html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{symbol} {interval} 戦略比較</title>
<script>{get_plotlyjs()}</script>
<style>
  body {{ margin:0; padding:16px; background:#0a0a12; font-family: 'Segoe UI',sans-serif; }}
  h1 {{ color:#eee; font-size:18px; margin:0 0 12px 0; }}
</style>
</head><body>
<h1>{symbol} {interval} &nbsp;戦略比較（リターン順）</h1>
{cardSections}
{dataScripts}
<script>{scriptParts}</script>
</body></html>"""

  outPath = Path("data") / "scalping" / f"compare_{symbol}_{interval}.html"
  outPath.parent.mkdir(parents=True, exist_ok=True)
  outPath.write_text(html, encoding="utf-8")
  print(f"\n比較チャート保存: {outPath}")

  import webbrowser
  webbrowser.open(str(outPath.resolve()))
