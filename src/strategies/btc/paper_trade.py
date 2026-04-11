"""
ペーパートレード: MAクロス戦略の疑似運用

毎日1回実行することで：
- 最新データを取得してシグナルを判定
- 買い/売りシグナル発生時にログへ記録
- 仮想資産の損益を追跡する

実際の注文は出さない。動作確認・戦略検証が目的。
"""

import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

# 戦略ロジックをbacktest.pyから再利用
from backtest import add_signals

DATA_DIR    = Path("data")
STATE_PATH  = DATA_DIR / "paper_state.json"
LOG_PATH    = DATA_DIR / "paper_log.csv"

SHORT_MA        = 5
LONG_MA         = 150
INITIAL_CAPITAL = 100_000  # USDT（バックテストと同じ単位）


# ---------- 状態管理 ----------

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # 初回起動時のデフォルト状態
    return {
        "capital":     INITIAL_CAPITAL,
        "holding":     0.0,   # 保有BTC量
        "entry_price": 0.0,
        "position":    "none",  # "long" or "none"
        "started_at":  datetime.now(timezone.utc).isoformat(),
        "last_run":    None,
        "last_price":  None,
    }


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ---------- ログ ----------

def append_log(dt, trade_type: str, price: float, capital: float, holding: float, pnl: float | None = None) -> None:
    row = pd.DataFrame([{
        "datetime":  dt,
        "type":      trade_type,
        "price":     price,
        "capital":   round(capital, 4),
        "holding":   round(holding, 8),
        "pnl_usdt":  round(pnl, 4) if pnl is not None else None,
    }])
    if LOG_PATH.exists():
        row.to_csv(LOG_PATH, mode="a", header=False, index=False)
    else:
        row.to_csv(LOG_PATH, index=False)


# ---------- データ取得 ----------

def fetch_latest() -> pd.DataFrame:
    """Binanceから最新の日足データを取得してCSVも更新する"""
    from fetch_btc import fetch_ohlcv, save_csv
    df = fetch_ohlcv(symbol="BTCUSDT", interval="1d", years=1)
    save_csv(df, str(DATA_DIR / "btc_1d.csv"))
    return df


# ---------- メイン ----------

def run() -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"=== ペーパートレード実行: {now_str} ===\n")

    # 最新データ取得 → シグナル付加
    print("最新データを取得中...")
    df = fetch_latest()
    df = add_signals(df, short=SHORT_MA, long=LONG_MA)

    # 最新の確定足（昨日）を参照
    latest    = df.iloc[-1]
    latest_dt = df.index[-1]
    price     = latest["close"]

    print(f"最新足  : {latest_dt.date()}  終値 ${price:,.0f}")
    print(f"MA{SHORT_MA:<4}: ${latest['ma_short']:,.0f}  "
          f"MA{LONG_MA}: ${latest['ma_long']:,.0f}")

    # 状態読み込み
    state   = load_state()
    capital = state["capital"]
    holding = state["holding"]

    print(f"ポジション: {state['position']}  "
          f"評価額 ${capital if holding == 0 else holding * price:,.0f}\n")

    # --- シグナル判定 ---
    # add_signals の position 列: 2=買いクロス, -2=売りクロス（backtest.pyと同じ定義）
    sig = latest["position"]

    if sig == 2 and state["position"] == "none":
        # 買いシグナル：全額投入
        holding            = capital / price
        state["entry_price"] = price
        capital            = 0.0
        state["position"]  = "long"
        print(f"*** 買いシグナル発生 ***")
        print(f"    価格: ${price:,.0f}  取得BTC: {holding:.6f}")
        append_log(latest_dt, "buy", price, capital, holding)

    elif sig == -2 and state["position"] == "long":
        # 売りシグナル：全BTC売却
        capital = holding * price
        pnl     = (price - state["entry_price"]) * (capital / price)  # USDT損益
        pnl_pct = (price / state["entry_price"] - 1) * 100
        print(f"*** 売りシグナル発生 ***")
        print(f"    価格: ${price:,.0f}  "
              f"損益: {pnl:+,.0f} USDT ({pnl_pct:+.1f}%)")
        append_log(latest_dt, "sell", price, capital, 0.0, pnl)
        state["position"]    = "none"
        holding              = 0.0
        state["entry_price"] = 0.0

    else:
        print("シグナルなし（ホールド / 待機中）")

    # --- サマリー ---
    portfolio_value = capital if holding == 0 else holding * price
    total_return    = (portfolio_value / INITIAL_CAPITAL - 1) * 100

    print(f"\n--- 現在の状態 ---")
    print(f"評価額   : ${portfolio_value:,.2f}")
    print(f"総リターン: {total_return:+.2f}%")
    if holding > 0 and state["entry_price"] > 0:
        unrealized = (price / state["entry_price"] - 1) * 100
        print(f"含み損益  : {unrealized:+.1f}%  "
              f"(エントリー ${state['entry_price']:,.0f})")

    # ログサマリー表示
    if LOG_PATH.exists():
        log = pd.read_csv(LOG_PATH)
        sells = log[log["type"] == "sell"]
        if not sells.empty:
            wins     = (sells["pnl_usdt"] > 0).sum()
            win_rate = wins / len(sells) * 100
            print(f"\n--- 累計 ---")
            print(f"トレード数: {len(sells)} 回  勝率: {win_rate:.0f}%")
            print(f"累計損益  : {sells['pnl_usdt'].sum():+,.2f} USDT")

    # 状態保存
    state["capital"]    = capital
    state["holding"]    = holding
    state["last_run"]   = datetime.now(timezone.utc).isoformat()
    state["last_price"] = price
    save_state(state)

    print(f"\n状態保存: {STATE_PATH}")
    print(f"ログ    : {LOG_PATH}")


if __name__ == "__main__":
    run()
