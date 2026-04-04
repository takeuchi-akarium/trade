"""
Binance公開APIからBTC/USDTの過去データを取得してCSV保存・チャート表示
取引所口座不要（公開エンドポイント）
"""

import requests
import pandas as pd
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

BINANCE_API = "https://api.binance.com/api/v3/klines"

INTERVALS = {
    "1m": "1分足",
    "5m": "5分足",
    "15m": "15分足",
    "1h": "1時間足",
    "4h": "4時間足",
    "1d": "日足",
}


def _fetch_batch(symbol: str, interval: str, end_time_ms: int | None = None) -> list:
    """1000本ずつ取得（ページネーション用）"""
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if end_time_ms:
        params["endTime"] = end_time_ms
    resp = requests.get(BINANCE_API, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


CANDLES_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040,
    "1h": 8_760, "4h": 2_190, "1d": 365,
}

def fetch_ohlcv(symbol: str = "BTCUSDT", interval: str = "1d", years: int = 1) -> pd.DataFrame:
    """Binanceから指定年数分のOHLCVデータを取得（ページネーション対応）"""
    all_raw = []
    end_time_ms = None

    candles_needed = CANDLES_PER_YEAR.get(interval, 365) * years
    batches_needed = -(- candles_needed // 1000)  # 切り上げ除算
    for _ in range(batches_needed):
        batch = _fetch_batch(symbol, interval, end_time_ms)
        if not batch:
            break
        all_raw = batch + all_raw
        end_time_ms = batch[0][0] - 1  # 最古の足の1ms前

    df = pd.DataFrame(all_raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df = df.drop_duplicates("open_time").sort_values("open_time")

    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df[["datetime", "open", "high", "low", "close", "volume"]].set_index("datetime")


def save_csv(df: pd.DataFrame, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    print(f"保存: {path}")


def plot_chart(df: pd.DataFrame, title: str = "BTC/USDT") -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(title, fontsize=14)

    # 終値チャート
    ax1.plot(df.index, df["close"], color="royalblue", linewidth=1.2, label="終値")
    ax1.set_ylabel("Price (USDT)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # 出来高
    ax2.bar(df.index, df["volume"], color="steelblue", alpha=0.6, width=0.8)
    ax2.set_ylabel("Volume")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    YEARS = 3
    print(f"BTC/USDT 日足データを取得中（過去{YEARS}年分）...")
    df = fetch_ohlcv(symbol="BTCUSDT", interval="1d", years=YEARS)

    print(f"取得件数: {len(df)} 本")
    print(f"期間: {df.index[0].date()} 〜 {df.index[-1].date()}")
    print(f"\n最新値:\n{df.tail(3)}")

    save_csv(df, "data/btc_1d.csv")
    plot_chart(df, f"BTC/USDT 日足 (過去{YEARS}年)")
