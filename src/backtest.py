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


def calc_equity_curve(df: pd.DataFrame, trades: list, initial_capital: float) -> pd.Series:
    """時系列の資産推移（%）を計算"""
    capital = initial_capital
    holding = 0.0
    equity = []
    buy_map = {t["datetime"]: t for t in trades if t["type"] == "buy"}
    sell_map = {t["datetime"]: t for t in trades if t["type"] == "sell"}

    for dt, row in df.iterrows():
        if dt in buy_map:
            holding = capital / row["close"]
            capital = 0
        elif dt in sell_map and holding > 0:
            capital = holding * row["close"]
            holding = 0
        val = capital if holding == 0 else holding * row["close"]
        equity.append(val)

    s = pd.Series(equity, index=df.index)
    return (s / initial_capital - 1) * 100


def plot_result(df: pd.DataFrame, trades: list, short: int, long: int, initial_capital: float = 100_000, output: str = "chart.html") -> None:
    equity_pct = calc_equity_curve(df, trades, initial_capital)
    bnh_pct = (df["close"] / df["close"].iloc[0] - 1) * 100

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=[f"BTC/USDT 移動平均クロス戦略 (MA{short} / MA{long})", "利益率 (%)", "シグナル"],
        vertical_spacing=0.04,
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

    # 利益率（戦略 vs バイアンドホールド）
    fig.add_trace(go.Scatter(
        x=df.index, y=bnh_pct, name="バイアンドホールド",
        line=dict(color="gray", width=1.2, dash="dash"),
        hovertemplate="%{x}<br>BnH: %{y:.1f}%<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=equity_pct, name="戦略リターン",
        fill="tozeroy", line=dict(color="gold", width=1.5),
        fillcolor="rgba(255,215,0,0.1)",
        hovertemplate="%{x}<br>戦略: %{y:.1f}%<extra></extra>",
    ), row=2, col=1)
    fig.add_hline(y=0, line=dict(color="white", width=0.5, dash="dot"), row=2, col=1)

    # シグナル
    fig.add_trace(go.Scatter(
        x=df.index, y=df["signal"], name="シグナル",
        fill="tozeroy", line=dict(color="purple", width=1),
        fillcolor="rgba(128,0,128,0.15)",
    ), row=3, col=1)

    fig.update_layout(
        height=800,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Price (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="利益率 (%)", row=2, col=1)
    fig.update_yaxes(title_text="Signal", row=3, col=1)

    # 任意の開始日から利益率を再計算するJavaScript
    # ズームやレンジ変更時に利益率パネルを開始点=0%に再正規化する
    dates_js = [str(d) for d in df.index]
    equity_js = equity_pct.tolist()
    bnh_js = bnh_pct.tolist()

    # BnH=trace[5], 戦略=trace[6]
    post_script = f"""
var _dates = {dates_js};
var _equity = {equity_js};
var _bnh = {bnh_js};

function findStartIdx(xStart) {{
    for (var i = 0; i < _dates.length; i++) {{
        if (_dates[i] >= xStart) return i;
    }}
    return 0;
}}

function renormalize(xStart) {{
    var idx = findStartIdx(xStart);
    var eBase = _equity[idx];
    var bBase = _bnh[idx];
    var gd = document.querySelector('.plotly-graph-div');
    Plotly.restyle(gd, {{y: [_bnh.map(function(v){{return v - bBase;}})]}}, [5]);
    Plotly.restyle(gd, {{y: [_equity.map(function(v){{return v - eBase;}})]}}, [6]);
}}

var gd = document.querySelector('.plotly-graph-div');
gd.on('plotly_relayout', function(e) {{
    var xStart = null;
    if (e['xaxis.range[0]']) xStart = e['xaxis.range[0]'];
    else if (e['xaxis.range']) xStart = e['xaxis.range'][0];
    if (xStart) renormalize(xStart);
    else {{
        // 全体表示に戻ったとき
        var gd2 = document.querySelector('.plotly-graph-div');
        Plotly.restyle(gd2, {{y: [_bnh]}}, [5]);
        Plotly.restyle(gd2, {{y: [_equity]}}, [6]);
    }}
}});
"""

    out_path = Path("data") / output
    fig.write_html(str(out_path), auto_open=True, post_script=post_script)
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

    plot_result(df, trades, SHORT_MA, LONG_MA, initial_capital=INITIAL_CAPITAL)
