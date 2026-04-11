"""
短期売買シミュレーション CLI

2つのモード:
  backtest  過去データでバックテスト
  live      リアルタイム常駐ペーパートレード

使用例:
  python src/scalping/run.py backtest --symbol BTCUSDT --strategy rsi --interval 5m
  python src/scalping/run.py backtest --symbol AAPL --strategy bb --interval 1d
  python src/scalping/run.py backtest --symbol BTCUSDT --compare --interval 5m
  python src/scalping/run.py live --symbol BTCUSDT --strategy rsi --interval 5m
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# プロジェクトルートをパスに追加
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from scalping.strategies import STRATEGIES, calcSignals, calcCombinedSignals
from scalping.backtest import runBacktest, calcMetrics, printMetrics, plotResult, plotCompare


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

BINANCE_SYMBOLS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"}

# Binance APIポーリング間隔（秒）
POLL_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _isBinanceSymbol(symbol: str) -> bool:
  return symbol.upper() in BINANCE_SYMBOLS or symbol.upper().endswith("USDT")


def fetchData(symbol: str, interval: str = "1d", years: int = 1) -> pd.DataFrame:
  """銘柄名から自動判定してデータ取得"""
  if _isBinanceSymbol(symbol):
    from btc.fetch_btc import fetch_ohlcv
    print(f"Binance APIから {symbol} {interval} を取得中...")
    return fetch_ohlcv(symbol=symbol.upper(), interval=interval, years=years)
  else:
    import yfinance as yf
    print(f"yfinanceから {symbol} を取得中...")
    periodMap = {1: "1y", 2: "2y", 3: "5y", 5: "5y"}
    period = periodMap.get(years, f"{years}y")
    # yfinanceのinterval制限: 1m=7日, 5m/15m=60日, 1h=730日
    yf_interval = interval
    if interval in ("1m", "5m", "15m"):
      period = "60d" if interval != "1m" else "7d"
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=yf_interval)
    df.columns = [c.lower() for c in df.columns]
    df.index.name = "datetime"
    # yfinanceの列名を統一
    if "adj close" in df.columns:
      df = df.drop(columns=["adj close"], errors="ignore")
    df = df.rename(columns={"stock splits": "stock_splits"}, errors="ignore")
    for col in ("dividends", "stock_splits", "capital gains"):
      df = df.drop(columns=[col], errors="ignore")
    return df[["open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------------
# バックテストモード
# ---------------------------------------------------------------------------

def cmdBacktest(args) -> None:
  df = fetchData(args.symbol, args.interval, args.years)
  print(f"取得件数: {len(df)} 本  期間: {df.index[0]} 〜 {df.index[-1]}")

  if args.compare:
    # 全戦略比較 — 1画面サマリー
    summaries = []
    for key, entry in STRATEGIES.items():
      dfS = calcSignals(df, key)
      trades, equity = runBacktest(dfS, args.capital, args.fee, args.sl, args.tp)
      metrics = calcMetrics(trades, equity, args.capital)

      # 月別勝率の推移を簡易表示用に集約
      ms = metrics["monthlyStats"]
      monthlyStr = "  ".join(f"{m['month']}:{m['winRate']:.0f}%" for m in ms[-6:]) if ms else "-"

      summaries.append({
        "key": key,
        "name": entry["name"],
        "return": metrics["totalReturn"],
        "final": metrics["finalValue"],
        "nTrades": metrics["totalTrades"],
        "winRate": metrics["winRate"],
        "pf": metrics["profitFactor"],
        "mdd": metrics["mdd"],
        "fees": metrics["totalFees"],
        "winRate20": metrics["winRate20"],
        "winRate50": metrics["winRate50"],
        "wrStability": metrics["winRateStability"],
        "monthlyTail": monthlyStr,
        "trades": trades,
        "equity": equity,
        "metrics": metrics,
      })

    # --- 1画面サマリー ---
    print(f"\n{'=' * 76}")
    print(f"  全戦略比較: {args.symbol} {args.interval}  "
          f"({df.index[0].strftime('%Y-%m-%d')} 〜 {df.index[-1].strftime('%Y-%m-%d')})")
    print(f"  初期資金: {args.capital:,.0f}  手数料: {args.fee}%"
          f"{'  SL: ' + str(args.sl) + '%' if args.sl else ''}"
          f"{'  TP: ' + str(args.tp) + '%' if args.tp else ''}")
    print(f"{'=' * 76}")

    # 全体パフォーマンス
    print(f"\n  {'戦略':<18s} {'リターン':>8s} {'最終資産':>10s} {'取引数':>6s} {'勝率':>7s} {'PF':>7s} {'MDD':>8s} {'手数料':>8s}")
    print(f"  {'-' * 72}")
    for s in summaries:
      print(f"  {s['name']:<18s} {s['return']:>+7.1f}% {s['final']:>10,.0f} {s['nTrades']:>6d} {s['winRate']:>6.1f}% {s['pf']:>7.2f} {s['mdd']:>7.1f}% {s['fees']:>8,.0f}")

    # 短期 vs 長期勝率
    print(f"\n  {'戦略':<18s} {'全期間':>7s} {'直近20件':>8s} {'直近50件':>8s} {'月別σ':>7s}  {'直近6ヶ月の月別勝率'}")
    print(f"  {'-' * 72}")
    for s in summaries:
      wr20 = f"{s['winRate20']:.0f}%" if s["winRate20"] is not None else "-"
      wr50 = f"{s['winRate50']:.0f}%" if s["winRate50"] is not None else "-"
      print(f"  {s['name']:<18s} {s['winRate']:>6.1f}% {wr20:>8s} {wr50:>8s} {s['wrStability']:>6.1f}%  {s['monthlyTail']}")

    # 1画面比較チャート
    plotCompare(df, summaries, args.capital, args.symbol, args.interval)

  else:
    # 単一戦略 or 複数AND
    strategyKeys = [s.strip() for s in args.strategy.split(",")]
    for key in strategyKeys:
      if key not in STRATEGIES:
        print(f"不明な戦略: {key}  選択肢: {', '.join(STRATEGIES.keys())}")
        return

    if len(strategyKeys) == 1:
      name = STRATEGIES[strategyKeys[0]]["name"]
      dfS = calcSignals(df, strategyKeys[0])
    else:
      name = " + ".join(STRATEGIES[k]["name"] for k in strategyKeys)
      dfS = calcCombinedSignals(df, strategyKeys)

    trades, equity = runBacktest(dfS, args.capital, args.fee, args.sl, args.tp)
    metrics = calcMetrics(trades, equity, args.capital)
    printMetrics(metrics, f"{name} | {args.symbol} {args.interval}")
    plotResult(df, trades, equity, args.capital, name, args.symbol, args.interval)


# ---------------------------------------------------------------------------
# リアルタイムモード（常駐）
# ---------------------------------------------------------------------------

STATE_DIR = ROOT / "data" / "scalping"
LOOKBACK = 200  # インジケータ計算に必要な直近足数


def _stateFile(symbol: str) -> Path:
  return STATE_DIR / f"state_{symbol}.json"


def _tradeLog(symbol: str) -> Path:
  return STATE_DIR / f"trades_{symbol}.csv"


def _loadState(symbol: str) -> dict:
  f = _stateFile(symbol)
  if f.exists():
    return json.loads(f.read_text(encoding="utf-8"))
  return {
    "capital": 100_000,
    "holding": 0.0,
    "entryPrice": 0.0,
    "totalTrades": 0,
    "wins": 0,
    "losses": 0,
    "totalPnl": 0.0,
    "peakCapital": 100_000,
    "trades": [],
  }


def _saveState(symbol: str, state: dict) -> None:
  STATE_DIR.mkdir(parents=True, exist_ok=True)
  _stateFile(symbol).write_text(
    json.dumps(state, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
  )


def _appendTradeLog(symbol: str, trade: dict) -> None:
  logFile = _tradeLog(symbol)
  header = not logFile.exists()
  STATE_DIR.mkdir(parents=True, exist_ok=True)
  with open(logFile, "a", encoding="utf-8") as f:
    if header:
      f.write("datetime,type,reason,price,pnl,capital\n")
    pnl = trade.get("pnl", "")
    cap = trade.get("capitalAfter", trade.get("holding", ""))
    f.write(f"{trade['datetime']},{trade['type']},{trade.get('reason','')},{trade['price']},{pnl},{cap}\n")


def _printLiveStatus(state: dict, symbol: str, price: float, signal: int) -> None:
  """ターミナルに現在状況を表示"""
  equity = state["capital"] if state["holding"] == 0 else state["holding"] * price
  totalReturn = (equity - 100_000) / 100_000 * 100
  nTrades = state["totalTrades"]
  winRate = state["wins"] / nTrades * 100 if nTrades > 0 else 0
  dd = (equity - state["peakCapital"]) / state["peakCapital"] * 100 if state["peakCapital"] > 0 else 0

  signalStr = {1: "▲ BUY", -1: "▼ SELL", 0: "― HOLD"}.get(signal, "―")
  posStr = f"保有中 @ {state['entryPrice']:,.0f}" if state["holding"] > 0 else "ノーポジ"

  now = datetime.now().strftime("%H:%M:%S")
  print(f"\r[{now}] {symbol} ${price:>10,.0f}  {signalStr:<8s}  {posStr:<24s}  "
        f"資産: {equity:>12,.0f}  リターン: {totalReturn:>+6.1f}%  "
        f"勝率: {winRate:>5.1f}% ({nTrades}件)  DD: {dd:>5.1f}%", end="", flush=True)


def cmdLive(args) -> None:
  strategyKeys = [s.strip() for s in args.strategy.split(",")]
  for key in strategyKeys:
    if key not in STRATEGIES:
      print(f"不明な戦略: {key}  選択肢: {', '.join(STRATEGIES.keys())}")
      return

  name = " + ".join(STRATEGIES[k]["name"] for k in strategyKeys)
  symbol = args.symbol
  interval = args.interval
  feeRate = args.fee / 100

  pollSec = POLL_INTERVALS.get(interval, 300)

  state = _loadState(symbol)
  if args.capital and state["capital"] == 100_000 and state["totalTrades"] == 0:
    state["capital"] = args.capital
    state["peakCapital"] = args.capital

  print(f"リアルタイムシミュレーション開始")
  print(f"  銘柄: {symbol}  戦略: {name}  間隔: {interval} ({pollSec}秒)")
  print(f"  初期資金: {state['capital']:,.0f}  手数料: {args.fee}%")
  if args.sl:
    print(f"  ストップロス: {args.sl}%")
  if args.tp:
    print(f"  テイクプロフィット: {args.tp}%")
  print(f"  Ctrl+C で停止\n")

  try:
    while True:
      try:
        df = fetchData(symbol, interval, years=1)
        df = df.tail(LOOKBACK)

        if len(strategyKeys) == 1:
          dfS = calcSignals(df, strategyKeys[0])
        else:
          dfS = calcCombinedSignals(df, strategyKeys)

        latestSignal = int(dfS["signal"].iloc[-1])
        latestPrice = float(dfS["close"].iloc[-1])
        now = datetime.now()

        # SL/TP判定
        if state["holding"] > 0:
          pnlPct = (latestPrice - state["entryPrice"]) / state["entryPrice"] * 100

          slHit = args.sl is not None and pnlPct <= -args.sl
          tpHit = args.tp is not None and pnlPct >= args.tp

          if slHit or tpHit:
            proceeds = state["holding"] * latestPrice
            fee = proceeds * feeRate
            state["capital"] = proceeds - fee
            reason = "stop_loss" if slHit else "take_profit"
            pnl = latestPrice - state["entryPrice"]
            state["totalTrades"] += 1
            if pnl > 0:
              state["wins"] += 1
            else:
              state["losses"] += 1
            state["totalPnl"] += pnl

            trade = {"datetime": now, "type": "sell", "reason": reason,
                     "price": latestPrice, "pnl": pnl, "capitalAfter": state["capital"]}
            _appendTradeLog(symbol, trade)
            state["holding"] = 0
            state["entryPrice"] = 0
            state["peakCapital"] = max(state["peakCapital"], state["capital"])
            _saveState(symbol, state)
            print(f"\n  {'SL' if slHit else 'TP'}発動 @ {latestPrice:,.0f}  損益: {pnl:+,.0f}")
            latestSignal = 0  # 同ティックでの再エントリー防止

        # 売りシグナル
        if latestSignal == -1 and state["holding"] > 0:
          proceeds = state["holding"] * latestPrice
          fee = proceeds * feeRate
          state["capital"] = proceeds - fee
          pnl = latestPrice - state["entryPrice"]
          state["totalTrades"] += 1
          if pnl > 0:
            state["wins"] += 1
          else:
            state["losses"] += 1
          state["totalPnl"] += pnl

          trade = {"datetime": now, "type": "sell", "reason": "signal",
                   "price": latestPrice, "pnl": pnl, "capitalAfter": state["capital"]}
          _appendTradeLog(symbol, trade)
          state["holding"] = 0
          state["entryPrice"] = 0
          state["peakCapital"] = max(state["peakCapital"], state["capital"])
          _saveState(symbol, state)
          print(f"\n  売り @ {latestPrice:,.0f}  損益: {pnl:+,.0f}")

        # 買いシグナル
        elif latestSignal == 1 and state["holding"] == 0:
          fee = state["capital"] * feeRate
          investable = state["capital"] - fee
          state["holding"] = investable / latestPrice
          state["entryPrice"] = latestPrice
          state["capital"] = 0

          trade = {"datetime": now, "type": "buy", "reason": "signal",
                   "price": latestPrice, "holding": state["holding"]}
          _appendTradeLog(symbol, trade)
          _saveState(symbol, state)
          print(f"\n  買い @ {latestPrice:,.0f}  数量: {state['holding']:.6f}")

        _printLiveStatus(state, symbol, latestPrice, latestSignal)

      except Exception as e:
        print(f"\n  エラー: {e}")

      time.sleep(pollSec)

  except KeyboardInterrupt:
    # 最終サマリー
    equity = state["capital"] if state["holding"] == 0 else state["holding"] * latestPrice
    totalReturn = (equity - state.get("peakCapital", 100_000)) / state.get("peakCapital", 100_000) * 100
    nTrades = state["totalTrades"]
    winRate = state["wins"] / nTrades * 100 if nTrades > 0 else 0

    print(f"\n\n{'=' * 50}")
    print(f"  シミュレーション終了")
    print(f"{'=' * 50}")
    print(f"  最終資産    : {equity:>12,.0f}")
    print(f"  総損益      : {state['totalPnl']:>+12,.0f}")
    print(f"  取引回数    : {nTrades:>12d}")
    print(f"  勝率        : {winRate:>11.1f}%")
    _saveState(symbol, state)
    print(f"\n  状態保存済み: {_stateFile(symbol)}")
    print(f"  取引ログ  : {_tradeLog(symbol)}")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def main():
  parser = argparse.ArgumentParser(description="短期売買シミュレーション")
  sub = parser.add_subparsers(dest="mode", required=True)

  # --- backtest ---
  bt = sub.add_parser("backtest", help="バックテスト")
  bt.add_argument("--symbol", required=True, help="銘柄 (BTCUSDT, AAPL, 7203.T等)")
  bt.add_argument("--strategy", default="rsi", help="戦略キー (rsi,bb,ema,vwap) カンマ区切りでAND合成")
  bt.add_argument("--interval", default="1d", help="タイムフレーム (1m,5m,15m,1h,1d)")
  bt.add_argument("--years", type=int, default=1, help="取得年数")
  bt.add_argument("--capital", type=float, default=100_000, help="初期資金")
  bt.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  bt.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  bt.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")
  bt.add_argument("--compare", action="store_true", help="全戦略比較モード")

  # --- live ---
  lv = sub.add_parser("live", help="リアルタイムシミュレーション")
  lv.add_argument("--symbol", required=True, help="銘柄 (BTCUSDT, AAPL等)")
  lv.add_argument("--strategy", default="rsi", help="戦略キー (rsi,bb,ema,vwap)")
  lv.add_argument("--interval", default="5m", help="タイムフレーム (1m,5m,15m,1h)")
  lv.add_argument("--capital", type=float, default=None, help="初期資金 (初回のみ有効)")
  lv.add_argument("--fee", type=float, default=0.1, help="手数料 (%%)")
  lv.add_argument("--sl", type=float, default=None, help="ストップロス (%%)")
  lv.add_argument("--tp", type=float, default=None, help="テイクプロフィット (%%)")

  args = parser.parse_args()

  if args.mode == "backtest":
    cmdBacktest(args)
  elif args.mode == "live":
    cmdLive(args)


if __name__ == "__main__":
  main()
