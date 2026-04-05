"""
Mid-Band Exit戦略のバックテスト

エントリー : 短期MA が 長期MA を上抜け（ゴールデンクロス）
エグジット : 以下のいずれか早い方
  1. 短期MA が 長期MA を下抜け（デッドクロス）
  2. 終値 < MA_long + (MA_short - MA_long) × threshold  ← Mid-Band Exit
     threshold=0.5 のとき MA_short と MA_long の中間点を下回ったら売り
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


def run_backtest(df: pd.DataFrame, initial_capital: float = 100_000, threshold: float | None = None, hwm: bool = False, reentry: bool = False) -> pd.DataFrame:
    """
    シンプルなバックテスト（全額投入・ロングのみ）
    initial_capital: 初期資金（円 or USDT）
    threshold: MAバンドストップのしきい値 (0〜1)
               stop_price = MA150 + (MA5 - MA150) * threshold
               None の場合はストップなし（MAクロスのみ）
    hwm:     True の場合、ストップラインを最高値基準で固定（一度上げたら下げない）
    reentry: True の場合、トレーリングストップ後に価格がストップラインを上抜けたら再エントリー
             （MA5 > MA150 のアップトレンド継続中のみ）
    """
    df = df.copy()
    capital = initial_capital
    holding = 0.0  # 保有BTC量
    entry_price = 0.0
    hwm_stop = 0.0  # ハイウォーターマーク（最高値基準ストップ）
    trail_exited = False  # トレーリングストップで退場したフラグ

    trades = []

    for dt, row in df.iterrows():
        if pd.isna(row["ma_long"]):
            continue

        current_stop = (
            row["ma_long"] + (row["ma_short"] - row["ma_long"]) * threshold
            if threshold is not None else None
        )

        # MAバンドトレーリングストップ（クロスより優先）
        if current_stop is not None and holding > 0:
            if hwm:
                hwm_stop = max(hwm_stop, current_stop)
                stop_price = hwm_stop
            else:
                stop_price = current_stop
            if row["close"] <= stop_price:
                capital = holding * row["close"]
                trades.append({
                    "datetime": dt, "type": "sell", "reason": "trail_stop",
                    "price": row["close"], "capital_after": capital,
                    "pnl": row["close"] - entry_price,
                })
                holding = 0
                entry_price = 0
                trail_exited = True
                continue  # 同日の買いクロスはスキップ

        # 再エントリー: トレーリングストップ退場後、ストップラインを上抜けたら買い直し
        if reentry and trail_exited and current_stop is not None and holding == 0:
            if row["signal"] == 1 and row["close"] > current_stop:
                holding = capital / row["close"]
                entry_price = row["close"]
                capital = 0
                hwm_stop = current_stop  # HWMをリセット
                trail_exited = False
                trades.append({"datetime": dt, "type": "buy", "reason": "reentry", "price": row["close"], "holding": holding})
                continue

        # 買いクロス
        if row["position"] == 2 and holding == 0:
            holding = capital / row["close"]
            entry_price = row["close"]
            capital = 0
            hwm_stop = 0.0  # エントリー時にリセット
            trail_exited = False
            trades.append({"datetime": dt, "type": "buy", "reason": "cross", "price": row["close"], "holding": holding})

        # 売りクロス
        elif row["position"] == -2 and holding > 0:
            capital = holding * row["close"]
            trades.append({
                "datetime": dt, "type": "sell", "reason": "cross",
                "price": row["close"], "capital_after": capital,
                "pnl": row["close"] - entry_price,
            })
            holding = 0
            entry_price = 0
            trail_exited = False

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


def plot_result(df: pd.DataFrame, trades: list, short: int, long: int, initial_capital: float = 100_000, output: str = "chart.html", threshold: float | None = None) -> None:
    equity_pct = calc_equity_curve(df, trades, initial_capital)
    bnh_pct = (df["close"] / df["close"].iloc[0] - 1) * 100

    if threshold is not None:
        title = f"BTC/USDT  Mid-Band Exit (MBE)  MA{short}/MA{long}  threshold={threshold}"
    else:
        title = f"BTC/USDT  MAクロス戦略  MA{short}/MA{long}"

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=[title, "利益率 (%)", "シグナル"],
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

    # MBEストップライン
    if threshold is not None:
        stop_line = df["ma_long"] + (df["ma_short"] - df["ma_long"]) * threshold
        fig.add_trace(go.Scatter(
            x=df.index, y=stop_line, name=f"MBE stop (th={threshold})",
            line=dict(color="orange", width=1, dash="dot"),
            hovertemplate="%{x}<br>Stop: $%{y:,.0f}<extra></extra>",
        ), row=1, col=1)

    # 買いポイント
    buys = [t for t in trades if t["type"] == "buy"]
    fig.add_trace(go.Scatter(
        x=[t["datetime"] for t in buys], y=[t["price"] for t in buys],
        mode="markers", name="買い",
        marker=dict(symbol="triangle-up", size=14, color="limegreen", line=dict(width=1, color="darkgreen")),
        hovertemplate="%{x}<br>買い: $%{y:,.0f}<extra></extra>",
    ), row=1, col=1)

    # 売りポイント（クロス）
    cross_sells = [t for t in trades if t["type"] == "sell" and t.get("reason") != "trail_stop"]
    if cross_sells:
        fig.add_trace(go.Scatter(
            x=[t["datetime"] for t in cross_sells], y=[t["price"] for t in cross_sells],
            mode="markers", name="売り(クロス)",
            marker=dict(symbol="triangle-down", size=14, color="red", line=dict(width=1, color="darkred")),
            hovertemplate="%{x}<br>売り(クロス): $%{y:,.0f}<br>損益: %{customdata:+,.0f} USDT<extra></extra>",
            customdata=[t["pnl"] for t in cross_sells],
        ), row=1, col=1)

    # 売りポイント（トレーリングストップ）
    trail_sells = [t for t in trades if t.get("reason") == "trail_stop"]
    if trail_sells:
        fig.add_trace(go.Scatter(
            x=[t["datetime"] for t in trail_sells], y=[t["price"] for t in trail_sells],
            mode="markers", name="売り(ストップ)",
            marker=dict(symbol="triangle-down", size=14, color="orange", line=dict(width=1, color="darkorange")),
            hovertemplate="%{x}<br>売り(ストップ): $%{y:,.0f}<br>損益: %{customdata:+,.0f} USDT<extra></extra>",
            customdata=[t["pnl"] for t in trail_sells],
        ), row=1, col=1)

    # 利益率（戦略 vs バイアンドホールド）- インデックスを動的に記録
    bnh_trace_idx = len(fig.data)
    fig.add_trace(go.Scatter(
        x=df.index, y=bnh_pct, name="バイアンドホールド",
        line=dict(color="gray", width=1.2, dash="dash"),
        hovertemplate="%{x}<br>BnH: %{y:.1f}%<extra></extra>",
    ), row=2, col=1)
    equity_trace_idx = len(fig.data)
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

    post_script = f"""
var _dates = {dates_js};
var _equity = {equity_js};
var _bnh = {bnh_js};
var _bnh_idx = {bnh_trace_idx};
var _eq_idx  = {equity_trace_idx};

var gd = document.querySelector('.plotly-graph-div');

// 期間リターン表示オーバーレイ（右上固定）
var _ov = document.createElement('div');
_ov.style.position = 'fixed';
_ov.style.top = '16px';
_ov.style.left = '24px';
_ov.style.background = 'rgba(20,20,20,0.88)';
_ov.style.color = '#fff';
_ov.style.padding = '8px 18px';
_ov.style.borderRadius = '6px';
_ov.style.border = '1px solid rgba(255,255,255,0.25)';
_ov.style.fontSize = '14px';
_ov.style.fontFamily = 'monospace';
_ov.style.lineHeight = '1.8';
_ov.style.zIndex = '9999';
document.body.appendChild(_ov);

function _getEndVal(idx) {{
    var t = gd.data[idx];
    if (!t || !t.y || !t.y.length) return null;
    return t.y[t.y.length - 1];
}}

function _fmt(v, colored) {{
    if (v === null || isNaN(v)) return '?';
    var s = v >= 0 ? '+' : '';
    var c = colored ? (v >= 0 ? '#4dff91' : '#ff5555') : '#aaa';
    return '<span style="color:' + c + '">' + s + v.toFixed(1) + '%</span>';
}}

function _updateOv() {{
    var e = _getEndVal(_eq_idx);
    var b = _getEndVal(_bnh_idx);
    _ov.innerHTML =
        '<span style="color:#888;font-size:11px">\\u671f\\u9593\\u30ea\\u30bf\\u30fc\\u30f3</span><br>' +
        '\\u6226\\u7565: ' + _fmt(e, true) + '<br>' +
        'BnH\\u00a0: ' + _fmt(b, false);
}}

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
    Plotly.restyle(gd, {{y: [_bnh.map(function(v){{return v - bBase;}})]}}, [_bnh_idx]);
    Plotly.restyle(gd, {{y: [_equity.map(function(v){{return v - eBase;}})]}}, [_eq_idx]);
}}

// 価格パネル（row1）のみY軸を自動スケール
var _ytimer = null;
var _yscaling = false;

function _toStr(x) {{
    if (typeof x === 'number') return new Date(x).toISOString().slice(0, 10);
    return String(x).slice(0, 10);
}}

function autoScalePriceY(xStart, xEnd) {{
    if (_yscaling) return;
    var xs = _toStr(xStart), xe = _toStr(xEnd);
    var yMin = Infinity, yMax = -Infinity;

    for (var i = 0; i < gd.data.length; i++) {{
        var trace = gd.data[i];
        if ((trace.yaxis || 'y') !== 'y') continue;  // 価格パネルのみ
        var tx = trace.x;
        if (!tx) continue;
        for (var j = 0; j < tx.length; j++) {{
            if (_toStr(tx[j]) < xs || _toStr(tx[j]) > xe) continue;
            if (trace.type === 'candlestick') {{
                if (trace.high && trace.high[j] != null) yMax = Math.max(yMax, trace.high[j]);
                if (trace.low  && trace.low[j]  != null) yMin = Math.min(yMin, trace.low[j]);
            }} else if (trace.y) {{
                var yv = trace.y[j];
                if (yv != null && !isNaN(yv)) {{
                    yMax = Math.max(yMax, yv);
                    yMin = Math.min(yMin, yv);
                }}
            }}
        }}
    }}

    if (yMin === Infinity) return;
    var pad = (yMax - yMin) * 0.05 || 1;
    _yscaling = true;
    Plotly.relayout(gd, {{
        'yaxis.range': [yMin - pad, yMax + pad],
        'yaxis.autorange': false
    }}).then(function() {{ _yscaling = false; }});
}}

function renormalize(xStart) {{
    var idx = findStartIdx(xStart);
    var eBase = _equity[idx];
    var bBase = _bnh[idx];
    // equity値を更新後、利益率パネルのY軸はautorangeに委ねる
    Promise.all([
        Plotly.restyle(gd, {{y: [_bnh.map(function(v){{return v - bBase;}})]}}, [_bnh_idx]),
        Plotly.restyle(gd, {{y: [_equity.map(function(v){{return v - eBase;}})]}}, [_eq_idx])
    ]).then(function() {{
        if (!_yscaling) Plotly.relayout(gd, {{'yaxis2.autorange': true}});
    }});
}}

setTimeout(_updateOv, 500);

gd.on('plotly_relayout', function(e) {{
    if (_yscaling) return;
    var xStart = null, xEnd = null;
    if (e['xaxis.range[0]'] !== undefined) {{ xStart = e['xaxis.range[0]']; xEnd = e['xaxis.range[1]']; }}
    else if (e['xaxis.range'])              {{ xStart = e['xaxis.range'][0]; xEnd = e['xaxis.range'][1]; }}

    if (!xStart) {{
        // リセット: equityを元に戻す、Y軸はPlotlyが自動復元
        clearTimeout(_ytimer);
        _yscaling = false;
        Plotly.restyle(gd, {{y: [_bnh]}}, [_bnh_idx]);
        Plotly.restyle(gd, {{y: [_equity]}}, [_eq_idx]);
        setTimeout(_updateOv, 80);
        return;
    }}

    renormalize(xStart);
    clearTimeout(_ytimer);
    _ytimer = setTimeout(function() {{ autoScalePriceY(xStart, xEnd); }}, 100);
    setTimeout(_updateOv, 80);
}});
"""

    out_path = Path("data") / output
    fig.write_html(str(out_path), auto_open=True, post_script=post_script)
    print(f"チャート保存: {out_path}")


if __name__ == "__main__":
    SHORT_MA = 5
    LONG_MA = 150
    THRESHOLD = 0.5   # MAバンドストップ: 0=MA150, 1=MA5, 0.5=中間
    INITIAL_CAPITAL = 100_000  # USDT（or 円）

    print(f"=== MA{SHORT_MA} / MA{LONG_MA} バックテスト ===\n")

    df = load_data("data/btc_1d.csv")
    df = add_signals(df, short=SHORT_MA, long=LONG_MA)
    df, trades, final_value = run_backtest(df, initial_capital=INITIAL_CAPITAL, threshold=THRESHOLD)
    metrics = calc_metrics(df, trades, INITIAL_CAPITAL, final_value)

    for k, v in metrics.items():
        print(f"{k:20s}: {v}")

    print(f"\n--- トレード履歴 ---")
    for t in trades:
        mark = "△買" if t["type"] == "buy" else "▽売"
        pnl_str = f"  損益: {t['pnl']:+.0f} USDT" if t["type"] == "sell" else ""
        print(f"{mark}  {t['datetime'].date()}  ${t['price']:,.0f}{pnl_str}")

    plot_result(df, trades, SHORT_MA, LONG_MA, initial_capital=INITIAL_CAPITAL, threshold=THRESHOLD, output=f"chart_MA{SHORT_MA}_{LONG_MA}_th{THRESHOLD}.html")
