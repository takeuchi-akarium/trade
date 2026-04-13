"""
ペアトレード バックテストエンジン

US100買い × US30売りのスプレッド損益をシミュレーション。
メトリクス算出 + Plotlyチャート出力。
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


# ---------------------------------------------------------------------------
# バックテスト実行
# ---------------------------------------------------------------------------

def runPairBacktest(
  df: pd.DataFrame,
  initialCapital: float = 1_000_000,
  feePct: float = 0.1,
  stopLossPct: float | None = None,
  takeProfitPct: float | None = None,
  nasdaqLots: float = 10,
  dowLots: float = 4,
) -> tuple[list[dict], pd.Series]:
  """
  ペアトレードのバックテスト。

  dfには spread, signal, nasdaq_close, dow_close が必要。
  signal=+1でペアエントリー、signal=-1でペアクローズ。

  損益はスプレッド変動（ロット加重リターン差）に基づく。

  Returns:
    trades: 取引履歴リスト
    equity: 時系列の資産額Series
  """
  capital = initialCapital
  inPosition = False
  entrySpreadCum = 0.0
  entryCapital = 0.0
  feeRate = feePct / 100

  trades = []
  equityList = []

  for dt, row in df.iterrows():
    signal = row.get("signal", 0)
    spreadCum = row["spread_cum"]

    # SL/TP判定（ポジション保有中）
    if inPosition:
      spreadPnl = spreadCum - entrySpreadCum
      # スプレッド変動をリターン%として扱う
      pnlPct = spreadPnl

      slHit = stopLossPct is not None and pnlPct <= -stopLossPct
      tpHit = takeProfitPct is not None and pnlPct >= takeProfitPct

      if slHit or tpHit:
        # ペアクローズ
        pnlAmount = entryCapital * (spreadPnl / 100)
        fee = abs(pnlAmount) * feeRate
        capital = entryCapital + pnlAmount - fee
        reason = "stop_loss" if slHit else "take_profit"
        trades.append({
          "datetime": dt, "type": "close", "reason": reason,
          "spreadCum": spreadCum,
          "pnl": pnlAmount,
          "pnlPct": pnlPct,
          "fee": fee,
          "capitalAfter": capital,
        })
        inPosition = False
        equityList.append((dt, capital))
        continue

    # クローズシグナル
    if signal == -1 and inPosition:
      spreadPnl = spreadCum - entrySpreadCum
      pnlPct = spreadPnl
      pnlAmount = entryCapital * (spreadPnl / 100)
      fee = abs(pnlAmount) * feeRate
      capital = entryCapital + pnlAmount - fee
      trades.append({
        "datetime": dt, "type": "close", "reason": "signal",
        "spreadCum": spreadCum,
        "pnl": pnlAmount,
        "pnlPct": pnlPct,
        "fee": fee,
        "capitalAfter": capital,
      })
      inPosition = False

    # エントリーシグナル
    elif signal == 1 and not inPosition:
      fee = capital * feeRate
      entryCapital = capital - fee
      entrySpreadCum = spreadCum
      capital = 0
      inPosition = True
      trades.append({
        "datetime": dt, "type": "entry", "reason": "signal",
        "spreadCum": spreadCum,
        "fee": fee,
        "entryCapital": entryCapital,
      })

    # 現在の資産評価
    if inPosition:
      unrealizedPnl = entryCapital * ((spreadCum - entrySpreadCum) / 100)
      val = entryCapital + unrealizedPnl
    else:
      val = capital
    equityList.append((dt, val))

  equity = pd.Series(
    [v for _, v in equityList],
    index=pd.DatetimeIndex([dt for dt, _ in equityList]),
  )
  return trades, equity


# ---------------------------------------------------------------------------
# メトリクス
# ---------------------------------------------------------------------------

def calcPairMetrics(
  trades: list[dict],
  equity: pd.Series,
  initialCapital: float,
) -> dict:
  """ペアトレードのメトリクス算出"""
  closeTrades = [t for t in trades if t["type"] == "close"]
  wins = [t for t in closeTrades if t["pnl"] > 0]
  losses = [t for t in closeTrades if t["pnl"] <= 0]
  nCloses = len(closeTrades)

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

  # 平均保有期間
  entryDates = {i: t["datetime"] for i, t in enumerate(trades) if t["type"] == "entry"}
  holdingDays = []
  entryIdx = 0
  for t in trades:
    if t["type"] == "entry":
      entryIdx = t["datetime"]
    elif t["type"] == "close":
      holdingDays.append((t["datetime"] - entryIdx).days)
  avgHolding = np.mean(holdingDays) if holdingDays else 0

  # 月別統計
  monthlyStats = _calcMonthlyStats(closeTrades)

  return {
    "initialCapital": initialCapital,
    "finalValue": finalValue,
    "totalReturn": totalReturn,
    "totalTrades": nCloses,
    "winRate": len(wins) / nCloses * 100 if nCloses else 0,
    "profitFactor": pf,
    "mdd": mdd,
    "totalFees": totalFees,
    "avgHoldingDays": avgHolding,
    "avgWin": np.mean([t["pnl"] for t in wins]) if wins else 0,
    "avgLoss": np.mean([t["pnl"] for t in losses]) if losses else 0,
    "monthlyStats": monthlyStats,
  }


def _calcMonthlyStats(closeTrades: list[dict]) -> list[dict]:
  """月別の勝率・損益を集計"""
  if not closeTrades:
    return []

  monthly = {}
  for t in closeTrades:
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


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

def printPairMetrics(metrics: dict) -> None:
  """メトリクスをターミナル表示"""
  print(f"\n{'=' * 60}")
  print(f"  US100買い × US30売り ペアトレード バックテスト")
  print(f"{'=' * 60}")

  print(f"\n【全体】")
  print(f"  初期資金        : {metrics['initialCapital']:>14,.0f}")
  print(f"  最終資産        : {metrics['finalValue']:>14,.0f}")
  print(f"  総リターン      : {metrics['totalReturn']:>13.2f}%")
  print(f"  トレード回数    : {metrics['totalTrades']:>14d}")
  print(f"  勝率            : {metrics['winRate']:>13.1f}%")
  print(f"  PF              : {metrics['profitFactor']:>14.2f}")
  print(f"  MDD             : {metrics['mdd']:>13.2f}%")
  print(f"  手数料合計      : {metrics['totalFees']:>14,.0f}")
  print(f"  平均保有日数    : {metrics['avgHoldingDays']:>13.1f}日")
  print(f"  平均利益        : {metrics['avgWin']:>+14,.0f}")
  print(f"  平均損失        : {metrics['avgLoss']:>+14,.0f}")

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

def plotPairResult(
  df: pd.DataFrame,
  trades: list[dict],
  equity: pd.Series,
  initialCapital: float,
  strategyName: str,
  output: str | None = None,
) -> None:
  """
  ペアトレード結果の可視化。

  Row1: ナスダック vs ダウ（正規化価格）
  Row2: 累積スプレッド + BB + 売買ポイント
  Row3: 資産推移
  """
  fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    row_heights=[0.30, 0.40, 0.30],
    subplot_titles=[
      "NASDAQ vs DOW（正規化）",
      f"累積スプレッド + {strategyName}",
      "資産推移 (%)",
    ],
    vertical_spacing=0.05,
  )

  # --- Row1: 正規化価格比較 ---
  nasdaqNorm = df["nasdaq_close"] / df["nasdaq_close"].iloc[0] * 100
  dowNorm = df["dow_close"] / df["dow_close"].iloc[0] * 100

  fig.add_trace(go.Scatter(
    x=df.index, y=nasdaqNorm, name="NASDAQ",
    line=dict(color="cyan", width=1.5),
  ), row=1, col=1)
  fig.add_trace(go.Scatter(
    x=df.index, y=dowNorm, name="DOW",
    line=dict(color="orange", width=1.5),
  ), row=1, col=1)

  # --- Row2: 累積スプレッド ---
  fig.add_trace(go.Scatter(
    x=df.index, y=df["spread_cum"], name="累積スプレッド",
    line=dict(color="white", width=1.5),
  ), row=2, col=1)

  # BB表示（BB戦略の場合）
  if "bb_upper" in df.columns:
    fig.add_trace(go.Scatter(
      x=df.index, y=df["bb_upper"], name="BB上",
      line=dict(color="red", width=0.8, dash="dot"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
      x=df.index, y=df["bb_lower"], name="BB下",
      line=dict(color="limegreen", width=0.8, dash="dot"),
      fill="tonexty", fillcolor="rgba(255,255,255,0.03)",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
      x=df.index, y=df["bb_mid"], name="BB中央",
      line=dict(color="gray", width=0.5, dash="dash"),
    ), row=2, col=1)

  # EMA表示
  if "ema_short" in df.columns:
    fig.add_trace(go.Scatter(
      x=df.index, y=df["ema_short"], name="EMA短期",
      line=dict(color="cyan", width=0.8),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
      x=df.index, y=df["ema_long"], name="EMA長期",
      line=dict(color="orange", width=0.8),
    ), row=2, col=1)

  # エントリー/クローズポイント
  entries = [t for t in trades if t["type"] == "entry"]
  closes = [t for t in trades if t["type"] == "close"]

  if entries:
    fig.add_trace(go.Scatter(
      x=[t["datetime"] for t in entries],
      y=[t["spreadCum"] for t in entries],
      mode="markers", name="エントリー",
      marker=dict(symbol="triangle-up", size=12, color="limegreen",
                  line=dict(width=1, color="white")),
    ), row=2, col=1)

  if closes:
    colors = {"signal": "red", "stop_loss": "orange", "take_profit": "cyan"}
    for reason, color in colors.items():
      pts = [t for t in closes if t.get("reason") == reason]
      if pts:
        label = {"signal": "クローズ", "stop_loss": "SL", "take_profit": "TP"}[reason]
        fig.add_trace(go.Scatter(
          x=[t["datetime"] for t in pts],
          y=[t["spreadCum"] for t in pts],
          mode="markers", name=label,
          marker=dict(symbol="triangle-down", size=12, color=color,
                      line=dict(width=1, color="white")),
        ), row=2, col=1)

  # --- Row3: 資産推移 ---
  equityPct = (equity / initialCapital - 1) * 100
  fig.add_trace(go.Scatter(
    x=equity.index, y=equityPct, name="戦略リターン",
    fill="tozeroy", line=dict(color="gold", width=1.5),
    fillcolor="rgba(255,215,0,0.1)",
  ), row=3, col=1)
  fig.add_hline(y=0, line=dict(color="white", width=0.5, dash="dot"), row=3, col=1)

  fig.update_layout(
    height=900,
    xaxis_rangeslider_visible=False,
    template="plotly_dark",
    hovermode="x unified",
  )
  fig.update_yaxes(title_text="正規化 (100=基準)", row=1, col=1)
  fig.update_yaxes(title_text="累積スプレッド", row=2, col=1)
  fig.update_yaxes(title_text="リターン (%)", row=3, col=1)

  if output is None:
    output = f"pair_us100_us30_{strategyName}.html"
  outPath = Path("data") / "scalping" / output
  outPath.parent.mkdir(parents=True, exist_ok=True)
  fig.write_html(str(outPath), auto_open=True)
  print(f"\nチャート保存: {outPath}")
