"""
移動平均クロス戦略のバックテスト
- 短期MA が 長期MA を上抜け → 買い
- 短期MA が 長期MA を下抜け → 売り
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from pathlib import Path

# Windows日本語フォント設定
_jp_fonts = ["MS Gothic", "Yu Gothic", "Meiryo", "BIZ UDGothic"]
for _f in _jp_fonts:
    if any(_f.lower() in x.name.lower() for x in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break


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


def plot_result(df: pd.DataFrame, trades: list, short: int, long: int) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(f"BTC/USDT 移動平均クロス戦略 (MA{short} / MA{long})", fontsize=13)

    # 価格とMA
    ax1.plot(df.index, df["close"], color="gray", linewidth=1, label="終値", alpha=0.8)
    ax1.plot(df.index, df["ma_short"], color="royalblue", linewidth=1.5, label=f"MA{short}")
    ax1.plot(df.index, df["ma_long"], color="tomato", linewidth=1.5, label=f"MA{long}")

    # 売買ポイント
    buys = [t for t in trades if t["type"] == "buy"]
    sells = [t for t in trades if t["type"] == "sell"]
    ax1.scatter([t["datetime"] for t in buys], [t["price"] for t in buys],
                marker="^", color="limegreen", s=120, zorder=5, label="買い")
    ax1.scatter([t["datetime"] for t in sells], [t["price"] for t in sells],
                marker="v", color="red", s=120, zorder=5, label="売り")

    ax1.set_ylabel("Price (USDT)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # シグナル
    ax2.plot(df.index, df["signal"], color="purple", linewidth=1)
    ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax2.fill_between(df.index, df["signal"], 0, where=df["signal"] > 0, alpha=0.3, color="green")
    ax2.fill_between(df.index, df["signal"], 0, where=df["signal"] < 0, alpha=0.3, color="red")
    ax2.set_ylabel("シグナル")
    ax2.set_yticks([-1, 0, 1])
    ax2.set_yticklabels(["売り", "-", "買い"])
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    SHORT_MA = 25
    LONG_MA = 75
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
