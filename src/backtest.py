"""
移動平均クロス戦略のバックテスト
- 短期MA が 長期MA を上抜け → 買い
- 短期MA が 長期MA を下抜け → 売り
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col="datetime", parse_dates=True)
    return df


def add_signals(df: pd.DataFrame, short: int = 25, long: int = 75) -> pd.DataFrame:
    df = df.copy()
    df["ma_short"] = df["close"].rolling(short).mean()
    df["ma_long"] = df["close"].rolling(long).mean()

    # 1: 買いシグナル、-1: 売りシグナル、0: ホールド
    df["signal"] = 0
    df.loc[df["ma_short"] > df["ma_long"], "signal"] = 1
    df.loc[df["ma_short"] < df["ma_long"], "signal"] = -1

    # シグナルが変化した時点だけ抽出（クロス）
    df["position"] = df["signal"].diff().fillna(0)
    return df


def run_backtest(df: pd.DataFrame, initial_capital: float = 100_000) -> pd.DataFrame:
    """
    シンプルなバックテスト（全額投入・ロングのみ）
    initial_capital: 初期資金（円 or USDT）
    """
    df = df.copy()
    capital = initial_capital
    holding = 0.0  # 保有BTC量
    entry_price = 0.0

    trades = []

    for dt, row in df.iterrows():
        if pd.isna(row["ma_long"]):
            continue

        # 買いクロス
        if row["position"] == 2 and holding == 0:
            holding = capital / row["close"]
            entry_price = row["close"]
            capital = 0
            trades.append({"datetime": dt, "type": "buy", "price": row["close"], "holding": holding})

        # 売りクロス
        elif row["position"] == -2 and holding > 0:
            capital = holding * row["close"]
            pnl = capital - initial_capital if len([t for t in trades if t["type"] == "sell"]) == 0 else capital - trades[-1].get("capital_after", initial_capital)
            trades.append({"datetime": dt, "type": "sell", "price": row["close"], "capital_after": capital, "pnl": row["close"] - entry_price})
            holding = 0
            entry_price = 0

    # 最終評価額（保有中なら時価）
    final_price = df["close"].iloc[-1]
    final_value = capital if holding == 0 else holding * final_price

    # 資産推移を計算
    df["portfolio_value"] = df.apply(
        lambda r: r["close"] * holding if holding > 0 else capital, axis=1
    )

    return df, trades, final_value


def calc_metrics(df: pd.DataFrame, trades: list, initial_capital: float, final_value: float) -> dict:
    total_return = (final_value - initial_capital) / initial_capital * 100

    sell_trades = [t for t in trades if t["type"] == "sell"]
    win_trades = [t for t in sell_trades if t["pnl"] > 0]
    win_rate = len(win_trades) / len(sell_trades) * 100 if sell_trades else 0

    # BTCのバイアンドホールドと比較
    first_price = df["close"].dropna().iloc[0]
    last_price = df["close"].iloc[-1]
    bnh_return = (last_price - first_price) / first_price * 100

    return {
        "初期資金": f"{initial_capital:,.0f}",
        "最終資産": f"{final_value:,.0f}",
        "総リターン": f"{total_return:.2f}%",
        "バイアンドホールド": f"{bnh_return:.2f}%",
        "トレード回数": len(sell_trades),
        "勝率": f"{win_rate:.1f}%",
    }


def plot_result(df: pd.DataFrame, trades: list, short: int, long: int, output: str = "chart.html") -> None:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        subplot_titles=[f"BTC/USDT 移動平均クロス戦略 (MA{short} / MA{long})", "シグナル"],
        vertical_spacing=0.05,
    )

    # ローソク足
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="BTC/USDT", increasing_line_color="limegreen", decreasing_line_color="tomato",
    ), row=1, col=1)

    # 移動平均線
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_short"], name=f"MA{short}",
                             line=dict(color="royalblue", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_long"], name=f"MA{long}",
                             line=dict(color="orange", width=1.5)), row=1, col=1)

    # 買いポイント
    buys = [t for t in trades if t["type"] == "buy"]
    fig.add_trace(go.Scatter(
        x=[t["datetime"] for t in buys], y=[t["price"] for t in buys],
        mode="markers", name="買い",
        marker=dict(symbol="triangle-up", size=14, color="limegreen", line=dict(width=1, color="darkgreen")),
        hovertemplate="%{x}<br>買い: $%{y:,.0f}<extra></extra>",
    ), row=1, col=1)

    # 売りポイント
    sells = [t for t in trades if t["type"] == "sell"]
    fig.add_trace(go.Scatter(
        x=[t["datetime"] for t in sells], y=[t["price"] for t in sells],
        mode="markers", name="売り",
        marker=dict(symbol="triangle-down", size=14, color="red", line=dict(width=1, color="darkred")),
        hovertemplate="%{x}<br>売り: $%{y:,.0f}<br>損益: %{customdata:+,.0f} USDT<extra></extra>",
        customdata=[t["pnl"] for t in sells],
    ), row=1, col=1)

    # シグナル
    fig.add_trace(go.Scatter(
        x=df.index, y=df["signal"], name="シグナル",
        fill="tozeroy", line=dict(color="purple", width=1),
        fillcolor="rgba(128,0,128,0.15)",
    ), row=2, col=1)

    fig.update_layout(
        height=700,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="Signal", row=2, col=1)

    out_path = Path("data") / output
    fig.write_html(str(out_path), auto_open=True)
    print(f"チャート保存: {out_path}")


if __name__ == "__main__":
    SHORT_MA = 5
    LONG_MA = 150
    INITIAL_CAPITAL = 100_000  # USDT（or 円）

    print(f"=== MA{SHORT_MA} / MA{LONG_MA} バックテスト ===\n")

    df = load_data("data/btc_1d.csv")
    df = add_signals(df, short=SHORT_MA, long=LONG_MA)
    df, trades, final_value = run_backtest(df, initial_capital=INITIAL_CAPITAL)
    metrics = calc_metrics(df, trades, INITIAL_CAPITAL, final_value)

    for k, v in metrics.items():
        print(f"{k:20s}: {v}")

    print(f"\n--- トレード履歴 ---")
    for t in trades:
        mark = "△買" if t["type"] == "buy" else "▽売"
        pnl_str = f"  損益: {t['pnl']:+.0f} USDT" if t["type"] == "sell" else ""
        print(f"{mark}  {t['datetime'].date()}  ${t['price']:,.0f}{pnl_str}")

    plot_result(df, trades, SHORT_MA, LONG_MA)
