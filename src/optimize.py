"""
MAパラメータ最適化
短期MA × 長期MAの全組み合わせをバックテストして成績比較
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from itertools import product
from pathlib import Path
from backtest import load_data, add_signals, run_backtest, calc_metrics

SHORT_RANGE = range(5, 51, 5)    # 5, 10, 15, ... 50
LONG_RANGE  = range(20, 201, 10) # 20, 30, 40, ... 200
INITIAL_CAPITAL = 100_000


def optimize(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    combos = [(s, l) for s, l in product(SHORT_RANGE, LONG_RANGE) if s < l]
    total = len(combos)

    for i, (short, long) in enumerate(combos, 1):
        print(f"\r検証中... {i}/{total} (MA{short}/MA{long})", end="", flush=True)
        try:
            df_s = add_signals(df, short=short, long=long)
            _, trades, final_value = run_backtest(df_s, initial_capital=INITIAL_CAPITAL)
            m = calc_metrics(df_s, trades, INITIAL_CAPITAL, final_value)
            sell_trades = [t for t in trades if t["type"] == "sell"]
            results.append({
                "short": short,
                "long": long,
                "return_pct": (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
                "final_value": final_value,
                "trades": len(sell_trades),
                "win_rate": len([t for t in sell_trades if t["pnl"] > 0]) / len(sell_trades) * 100 if sell_trades else 0,
            })
        except Exception:
            pass

    print()
    return pd.DataFrame(results).sort_values("return_pct", ascending=False)


def plot_heatmap(results_df: pd.DataFrame) -> None:
    pivot = results_df.pivot(index="short", columns="long", values="return_pct")

    fig = make_subplots(rows=1, cols=1)
    fig.add_trace(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale="RdYlGn",
        zmid=0,
        text=[[f"{v:.0f}%" for v in row] for row in pivot.values],
        texttemplate="%{text}",
        textfont={"size": 10},
        hovertemplate="MA短期: %{y}<br>MA長期: %{x}<br>リターン: %{z:.2f}%<extra></extra>",
        colorbar=dict(title="リターン(%)"),
    ))
    fig.update_layout(
        title="MAパラメータ最適化ヒートマップ（リターン%）",
        xaxis_title="長期MA",
        yaxis_title="短期MA",
        template="plotly_dark",
        height=600,
    )
    out = Path("data/optimize_heatmap.html")
    fig.write_html(str(out), auto_open=True)
    print(f"ヒートマップ保存: {out}")


def plot_top_results(df: pd.DataFrame, results_df: pd.DataFrame, top_n: int = 5) -> None:
    fig = go.Figure()

    # バイアンドホールド
    first_price = df["close"].iloc[0]
    bnh = (df["close"] / first_price - 1) * 100
    fig.add_trace(go.Scatter(
        x=df.index, y=bnh,
        name="バイアンドホールド",
        line=dict(color="gray", width=1.5, dash="dash"),
    ))

    # 上位N戦略の資産推移
    colors = ["gold", "royalblue", "limegreen", "tomato", "violet"]
    for i, (_, row) in enumerate(results_df.head(top_n).iterrows()):
        short, long = int(row["short"]), int(row["long"])
        df_s = add_signals(df, short=short, long=long)
        _, trades, _ = run_backtest(df_s, initial_capital=INITIAL_CAPITAL)

        # 資産推移を再計算
        capital = INITIAL_CAPITAL
        holding = 0.0
        equity = []
        for dt, r in df_s.iterrows():
            if pd.isna(r["ma_long"]):
                equity.append((dt, INITIAL_CAPITAL))
                continue
            if r["position"] == 2 and holding == 0:
                holding = capital / r["close"]
                capital = 0
            elif r["position"] == -2 and holding > 0:
                capital = holding * r["close"]
                holding = 0
            val = capital if holding == 0 else holding * r["close"]
            equity.append((dt, val))

        eq_df = pd.DataFrame(equity, columns=["dt", "value"])
        eq_pct = (eq_df["value"] / INITIAL_CAPITAL - 1) * 100

        fig.add_trace(go.Scatter(
            x=eq_df["dt"], y=eq_pct,
            name=f"MA{short}/{long} ({row['return_pct']:.0f}%)",
            line=dict(color=colors[i], width=1.5),
        ))

    fig.update_layout(
        title=f"上位{top_n}戦略の資産推移 vs バイアンドホールド",
        yaxis_title="リターン(%)",
        template="plotly_dark",
        hovermode="x unified",
        height=500,
    )
    out = Path("data/optimize_equity.html")
    fig.write_html(str(out), auto_open=True)
    print(f"資産推移グラフ保存: {out}")


if __name__ == "__main__":
    print("データ読み込み中...")
    df = load_data("data/btc_1d.csv")

    print(f"最適化開始: 短期MA {list(SHORT_RANGE)} × 長期MA {list(LONG_RANGE)}")
    results_df = optimize(df)

    print("\n=== 上位10結果 ===")
    print(results_df.head(10).to_string(index=False))

    print("\n=== 下位5結果 ===")
    print(results_df.tail(5).to_string(index=False))

    plot_heatmap(results_df)
    plot_top_results(df, results_df, top_n=5)
