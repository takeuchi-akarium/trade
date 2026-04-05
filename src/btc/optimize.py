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
from backtest import load_data, add_signals, run_backtest, calc_metrics, calc_equity_curve

SHORT_RANGE     = range(5, 51, 5)    # 5, 10, 15, ... 50
LONG_RANGE      = range(20, 201, 10) # 20, 30, 40, ... 200
THRESHOLD_RANGE = np.round(np.arange(0.1, 1.0, 0.1), 2)  # 0.1 〜 0.9
INITIAL_CAPITAL = 100_000

# thresholdを最適化する際の固定MAパラメータ
FIXED_SHORT = 5
FIXED_LONG  = 150


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


def optimize_threshold(df: pd.DataFrame, short: int = FIXED_SHORT, long: int = FIXED_LONG) -> pd.DataFrame:
    """MA固定でthresholdをグリッドサーチ。当日基準・HWM基準・クロスのみを比較"""
    df_s = add_signals(df, short=short, long=long)
    results = []

    def _record(label, mode, th, trades, fv):
        sells = [t for t in trades if t["type"] == "sell"]
        trail = len([t for t in sells if t.get("reason") == "trail_stop"])
        return {
            "threshold": th,
            "mode": mode,
            "label": label,
            "return_pct": (fv - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
            "trades": len(sells),
            "win_rate": len([t for t in sells if t["pnl"] > 0]) / len(sells) * 100 if sells else 0,
            "trail_stop_count": trail,
        }

    # ベースライン: クロスのみ
    _, trades, fv = run_backtest(df_s, initial_capital=INITIAL_CAPITAL, threshold=None)
    results.append(_record("クロスのみ", "cross", None, trades, fv))

    # threshold × 当日基準 / HWM基準 / HWM+再エントリー
    for th in THRESHOLD_RANGE:
        _, trades, fv = run_backtest(df_s, initial_capital=INITIAL_CAPITAL, threshold=th, hwm=False)
        results.append(_record(f"{th:.1f}(当日)", "current", th, trades, fv))

        _, trades, fv = run_backtest(df_s, initial_capital=INITIAL_CAPITAL, threshold=th, hwm=True)
        results.append(_record(f"{th:.1f}(HWM)", "hwm", th, trades, fv))

        _, trades, fv = run_backtest(df_s, initial_capital=INITIAL_CAPITAL, threshold=th, hwm=True, reentry=True)
        results.append(_record(f"{th:.1f}(HWM+再)", "hwm_reentry", th, trades, fv))

    return pd.DataFrame(results)


def plot_threshold_results(df: pd.DataFrame, results_df: pd.DataFrame, short: int = FIXED_SHORT, long: int = FIXED_LONG) -> None:
    """threshold別リターン比較（当日 vs HWM）+ 最良戦略の資産推移"""
    df_s = add_signals(df, short=short, long=long)
    bnh  = (df_s["close"] / df_s["close"].iloc[0] - 1) * 100

    baseline      = results_df[results_df["mode"] == "cross"].iloc[0]["return_pct"]
    current_rows  = results_df[results_df["mode"] == "current"]
    hwm_rows      = results_df[results_df["mode"] == "hwm"]
    hwmre_rows    = results_df[results_df["mode"] == "hwm_reentry"]

    # 各方式の最良threshold
    best_current = current_rows.sort_values("return_pct", ascending=False).iloc[0]
    best_hwm     = hwm_rows.sort_values("return_pct", ascending=False).iloc[0]
    best_hwmre   = hwmre_rows.sort_values("return_pct", ascending=False).iloc[0]

    # 資産推移
    _, tr_base,  _ = run_backtest(df_s, INITIAL_CAPITAL, threshold=None)
    _, tr_cur,   _ = run_backtest(df_s, INITIAL_CAPITAL, threshold=best_current["threshold"], hwm=False)
    _, tr_hwm,   _ = run_backtest(df_s, INITIAL_CAPITAL, threshold=best_hwm["threshold"],     hwm=True)
    _, tr_hwmre, _ = run_backtest(df_s, INITIAL_CAPITAL, threshold=best_hwmre["threshold"],   hwm=True, reentry=True)

    eq_base  = calc_equity_curve(df_s, tr_base,  INITIAL_CAPITAL)
    eq_cur   = calc_equity_curve(df_s, tr_cur,   INITIAL_CAPITAL)
    eq_hwm   = calc_equity_curve(df_s, tr_hwm,   INITIAL_CAPITAL)
    eq_hwmre = calc_equity_curve(df_s, tr_hwmre, INITIAL_CAPITAL)

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.45, 0.55],
        subplot_titles=[
            f"threshold別リターン: 当日 / HWM / HWM+再エントリー (MA{short}/{long})",
            f"資産推移比較（各方式のbest threshold）",
        ],
        vertical_spacing=0.1,
    )

    # --- 上段: 3方式の折れ線 ---
    for rows, name, color in [
        (current_rows, "当日基準",       "royalblue"),
        (hwm_rows,     "HWM基準",        "gold"),
        (hwmre_rows,   "HWM+再エントリー", "limegreen"),
    ]:
        fig.add_trace(go.Scatter(
            x=rows["label"], y=rows["return_pct"],
            name=name, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=8),
            hovertemplate=f"%{{x}}<br>{name}: %{{y:.1f}}%<extra></extra>",
        ), row=1, col=1)

    fig.add_hline(
        y=baseline,
        line=dict(color="white", width=1.5, dash="dash"),
        annotation_text=f"クロスのみ {baseline:.1f}%",
        annotation_position="top left",
        row=1, col=1,
    )

    # --- 下段: 資産推移 ---
    fig.add_trace(go.Scatter(
        x=df_s.index, y=bnh, name="バイアンドホールド",
        line=dict(color="gray", width=1.2, dash="dash"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df_s.index, y=eq_base,
        name=f"クロスのみ ({baseline:.1f}%)",
        line=dict(color="white", width=1.2),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df_s.index, y=eq_cur,
        name=f"当日 th={best_current['threshold']:.1f} ({best_current['return_pct']:.1f}%)",
        line=dict(color="royalblue", width=1.8),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df_s.index, y=eq_hwm,
        name=f"HWM th={best_hwm['threshold']:.1f} ({best_hwm['return_pct']:.1f}%)",
        line=dict(color="gold", width=1.8),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df_s.index, y=eq_hwmre,
        name=f"HWM+再 th={best_hwmre['threshold']:.1f} ({best_hwmre['return_pct']:.1f}%)",
        line=dict(color="limegreen", width=1.8),
    ), row=2, col=1)

    fig.update_layout(
        height=780,
        template="plotly_dark",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="リターン(%)", row=1, col=1)
    fig.update_yaxes(title_text="リターン(%)", row=2, col=1)

    out = Path(__file__).parent.parent / "data" / "threshold_comparison.html"
    fig.write_html(str(out), auto_open=True)
    print(f"比較チャート保存: {out}")


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

    # --- thresholdの最適化 ---
    print(f"\n=== thresholdの最適化 (MA{FIXED_SHORT}/{FIXED_LONG}) ===")
    th_results = optimize_threshold(df, short=FIXED_SHORT, long=FIXED_LONG)
    print(th_results.to_string(index=False))

    plot_threshold_results(df, th_results, short=FIXED_SHORT, long=FIXED_LONG)
