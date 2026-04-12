"""
自動売買エンジン（複数戦略同時稼働）

各戦略が独立して判定・発注。資金はweight比率で配分。
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from exchange.gmo import GmoExchange
from trader.risk import RiskManager

STATE_DIR = ROOT / "data" / "trader"
JST = timezone(timedelta(hours=9))

# レジーム別weight%（config.yamlで上書き可能）
DEFAULT_REGIME_WEIGHTS = {
  "uptrend":   {"bb": 30, "ema_don": 70, "bb_ls": 0},   # ema+don主役、bbは押し目
  "range":     {"bb": 70, "ema_don": 10, "bb_ls": 20},   # bb主体、ema_don少量
  "downtrend": {"bb": 0,  "ema_don": 0,  "bb_ls": 0},    # 全退避（デフォルト）
  # bb_lsを下げ基調で使うには config.yaml で downtrend の bb_ls を設定
}

# ファンダ補正時のweight
FUNDA_BOOST_WEIGHTS = {
  "uptrend_boost": {"bb": 10, "ema_don": 90, "bb_ls": 0},  # 両方強気→ema_don全力
  "range_boost":   {"bb": 60, "ema_don": 20, "bb_ls": 20},  # レンジ+ファンダ強気→ema_don増量
}


def detectRegime(price: float, trendMa: float, threshold: float = 2.0) -> str:
  """短期MAとの乖離率でレジーム判定"""
  if trendMa is None or trendMa == 0:
    return "range"
  if price > trendMa * (1 + threshold / 100):
    return "uptrend"
  elif price < trendMa * (1 - threshold / 100):
    return "downtrend"
  return "range"


def adjustRegimeByFunda(regime: str, sma50Dev: float, fundaScore: float,
                        upZone: float = 5.0, downZone: float = -10.0,
                        fundaThr: float = 0.3, boostThr: float = 0.5) -> tuple[str, dict | None]:
  """
  ファンダスコアでレジーム判定を補正する。

  Early Transition:
    上昇圏(0~upZone%) + ファンダ弱気 → rangeに早期退避
    下落圏(0~downZone%) + ファンダ強気 → rangeに留まる（全退避しない）

  Boost:
    uptrend + ファンダ強気(>boostThr) → ema90%にブースト
    range + ファンダ強気(>boostThr) → ema20%に増量

  戻り値: (補正後regime, weight上書きdict or None)
  """
  if fundaScore is None:
    return regime, None

  # Early Transition: 上昇圏でファンダ弱気 → range退避
  if sma50Dev is not None and sma50Dev > 0 and sma50Dev < upZone and fundaScore < -fundaThr:
    return "range", None

  # Early Transition: 下落圏でファンダ強気 → range留まり
  if sma50Dev is not None and sma50Dev < 0 and sma50Dev > downZone and fundaScore > fundaThr:
    return "range", None

  # Boost: uptrend + ファンダ強気
  if regime == "uptrend" and fundaScore > boostThr:
    return "uptrend", FUNDA_BOOST_WEIGHTS["uptrend_boost"]

  # Boost: range + ファンダ強気
  if regime == "range" and fundaScore > boostThr:
    return "range", FUNDA_BOOST_WEIGHTS["range_boost"]

  return regime, None


def _getRegimeWeight(strategyName: str, regime: str, regimeWeights: dict) -> float:
  """レジームに応じたweight%を取得"""
  return regimeWeights.get(regime, {}).get(strategyName, 0)


ENTRY_CONFIRM_RETRIES = 5
ENTRY_CONFIRM_INTERVAL = 2    # エントリー: 2秒×5=10秒で見送り
CLOSE_CONFIRM_RETRIES = 10
CLOSE_CONFIRM_INTERVAL = 6   # 決済: 6秒×10=60秒粘ってから成行


def _waitExecution(exchange, orderId: str, retries: int = ENTRY_CONFIRM_RETRIES, interval: int = ENTRY_CONFIRM_INTERVAL) -> bool:
  """注文の約定をポーリングで確認。約定したらTrue"""
  for _ in range(retries):
    time.sleep(interval)
    try:
      execs = exchange.getExecutions(orderId=orderId)
      if execs:
        return True
    except Exception:
      pass
  return False


def _stateFile(strategyName: str) -> Path:
  return STATE_DIR / f"state_{strategyName}.json"


def _loadState(strategyName: str) -> dict:
  f = _stateFile(strategyName)
  if f.exists():
    return json.loads(f.read_text(encoding="utf-8"))
  return {
    "strategy": strategyName,
    "position": "none",  # "none", "long", "short"
    "entryPrice": 0,
    "entrySize": 0,
    "stopOrderId": None,
    "stopPrice": 0,
    "totalTrades": 0,
    "wins": 0,
    "losses": 0,
    "totalPnl": 0,
    "trades": [],  # 直近500件のみ保持
  }


MAX_TRADES_HISTORY = 500  # メモリ肥大化防止のため直近N件のみ保持


def _saveState(strategyName: str, state: dict) -> None:
  STATE_DIR.mkdir(parents=True, exist_ok=True)
  # tradesが上限を超えたら古いものを切り捨て
  if len(state.get("trades", [])) > MAX_TRADES_HISTORY:
    state["trades"] = state["trades"][-MAX_TRADES_HISTORY:]
  state["updatedAt"] = datetime.now(JST).isoformat()
  _stateFile(strategyName).write_text(
    json.dumps(state, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )


def _notify(message: str, config: dict) -> None:
  try:
    from common.notifier import notify
    notify(message, config)
  except Exception as e:
    print(f"  [notify fail] {e}")


def _runStrategy(sCfg: dict, exchange, ticker, price, totalEquity, availableJpy, config: dict, dryRun: bool, riskMgr: RiskManager = None) -> dict:
  """1つの戦略を実行"""
  strategyName = sCfg["name"]
  mode = sCfg.get("mode", "long")
  interval = sCfg.get("interval", "1d")
  weight = sCfg.get("weight", 50)
  params = sCfg.get("params", {})
  symbol = config.get("trader", {}).get("symbol", "BTC")
  riskCfg = config.get("trader", {}).get("risk", {})

  # 発注可能額はJPY残高ベース（BTC評価額を含めない）
  allocatedCapital = availableJpy * weight / 100
  state = _loadState(strategyName)

  print(f"\n  --- {strategyName} ({mode}, {interval}, {weight}%) ---")

  # シグナル生成
  import strategies
  from strategies.registry import getStrategy
  strategy = getStrategy(strategyName)

  # グリッド戦略はシグナルベースではない（エンジン外で処理）
  if strategyName == "grid":
    print(f"    Grid: allocated {allocatedCapital:,.0f} JPY (grid runs independently)")
    _saveState(strategyName, state)
    return {"action": "GRID", "detail": "grid runs on its own cycle"}

  data = strategy.fetchData(symbol=f"{symbol}USDT", interval=interval, years=1)
  data = data.tail(200)
  dfS = strategy.generateSignals(data, **params)
  signal = int(dfS["signal"].iloc[-1])
  signalStr = {1: "BUY", -1: "SELL", 0: "HOLD"}.get(signal, "?")
  print(f"    signal: {signalStr}  price: {price:,.0f}")

  action = "HOLD"
  detail = ""

  # === BUYシグナル ===
  if signal == 1 and state["position"] != "long":
    # ショート保有中なら先に決済
    if state["position"] == "short" and state["entrySize"] > 0:
      action, detail = _closePosition(state, exchange, ticker, price, symbol, riskCfg, dryRun, "short")
      # 決済失敗（position未変更）ならエントリーしない
      if state["position"] != "none":
        print(f"    決済未完了のためエントリーをスキップ")
        _saveState(strategyName, state)
        return {"action": action, "detail": detail}

    # ロングエントリー
    ok, size, msg = riskMgr.checkBeforeOrder(allocatedCapital, price, allocatedCapital)
    if ok:
      action = "BUY"
      orderPrice = int(ticker["ask"])
      detail = f"BUY {orderPrice:,} x {size} BTC"

      if not dryRun:
        result = exchange.orderLimit(symbol, "BUY", orderPrice, size)
        orderId = str(result) if result else None
        detail += f" -> orderId:{orderId}"
        # 約定確認
        if not _waitExecution(exchange, orderId):
          detail += " (未約定 — キャンセル試行)"
          try:
            exchange.cancelOrder(orderId)
          except Exception:
            pass
          print(f"    -> FAIL: {detail}")
          _saveState(strategyName, state)
          return {"action": "FAIL", "detail": detail}

      # 逆指値
      slPct = riskCfg.get("stop_loss_pct", 5)
      stopPrice = int(orderPrice * (1 - slPct / 100))
      detail += f" + SL {stopPrice:,}"
      if not dryRun:
        try:
          slResult = exchange.orderStop(symbol, "SELL", stopPrice, size)
          state["stopOrderId"] = str(slResult)
        except Exception as e:
          detail += f" (SL fail: {e})"

      state["position"] = "long"
      state["entryPrice"] = orderPrice
      state["entrySize"] = size
      state["stopPrice"] = stopPrice
      state["trades"].append({
        "datetime": datetime.now(JST).isoformat(),
        "type": "buy", "price": orderPrice, "size": size, "dryRun": dryRun,
      })
    else:
      detail = msg

  # === SELLシグナル ===
  elif signal == -1:
    # ロング保有中なら決済
    if state["position"] == "long" and state["entrySize"] > 0:
      action, detail = _closePosition(state, exchange, ticker, price, symbol, riskCfg, dryRun, "long")
      if state["position"] != "none":
        print(f"    決済未完了のためショートエントリーをスキップ")
        _saveState(strategyName, state)
        return {"action": action, "detail": detail}

    # L/Sモードならショートエントリー
    if mode == "long_short" and state["position"] == "none":
      ok, size, msg = riskMgr.checkBeforeOrder(allocatedCapital, price, allocatedCapital)
      if ok:
        action = "SHORT"
        orderPrice = int(ticker["bid"])
        detail += f" -> SHORT {orderPrice:,} x {size} BTC"

        if not dryRun:
          result = exchange.orderLimit(symbol, "SELL", orderPrice, size)
          orderId = str(result) if result else None
          detail += f" -> orderId:{orderId}"
          if not _waitExecution(exchange, orderId):
            detail += " (未約定 — キャンセル試行)"
            try:
              exchange.cancelOrder(orderId)
            except Exception:
              pass
            print(f"    -> FAIL: {detail}")
            _saveState(strategyName, state)
            return {"action": "FAIL", "detail": detail}

        # 逆指値（ショート用: 上方向にストップ）
        slPct = riskCfg.get("stop_loss_pct", 5)
        stopPrice = int(orderPrice * (1 + slPct / 100))
        detail += f" + SL {stopPrice:,}"
        if not dryRun:
          try:
            slResult = exchange.orderStop(symbol, "BUY", stopPrice, size)
            state["stopOrderId"] = str(slResult)
          except Exception as e:
            detail += f" (SL fail: {e})"

        state["position"] = "short"
        state["entryPrice"] = orderPrice
        state["entrySize"] = size
        state["stopPrice"] = stopPrice
        state["trades"].append({
          "datetime": datetime.now(JST).isoformat(),
          "type": "short", "price": orderPrice, "size": size, "dryRun": dryRun,
        })

  else:
    detail = f"pos:{state['position']} sig:{signalStr}"

  print(f"    -> {action}: {detail}")
  _saveState(strategyName, state)

  # Discord通知
  if action in ("BUY", "SELL", "SHORT"):
    icon = {"BUY": "+", "SELL": "-", "SHORT": "v"}.get(action, "")
    msg = f"[{icon}] **{strategyName}** {action} {symbol}\n  {detail}"
    if dryRun:
      msg = f"[DRY] {msg}"
    _notify(msg, config)

  return {"action": action, "detail": detail}


def _closePosition(state, exchange, ticker, price, symbol, riskCfg, dryRun, side):
  """ポジション決済"""
  size = state["entrySize"]
  entryPrice = state["entryPrice"]

  if side == "long":
    orderPrice = int(ticker["bid"])
    pnl = (orderPrice - entryPrice) * size
    detail = f"CLOSE LONG {orderPrice:,} x {size} pnl:{pnl:+,.0f}"
    orderSide = "SELL"
  else:
    orderPrice = int(ticker["ask"])
    pnl = (entryPrice - orderPrice) * size
    detail = f"CLOSE SHORT {orderPrice:,} x {size} pnl:{pnl:+,.0f}"
    orderSide = "BUY"

  if not dryRun:
    # 逆指値キャンセル（失敗時は決済を中止）
    slId = state.get("stopOrderId")
    if slId:
      try:
        exchange.cancelOrder(slId)
      except Exception as e:
        detail += f" (SLキャンセル失敗: {e} — 決済中止)"
        return "ERROR", detail
    try:
      result = exchange.orderLimit(symbol, orderSide, orderPrice, size)
      orderId = str(result) if result else None
      # 決済は長めに待つ（60秒）。それでも未約定なら成行にフォールバック
      if not _waitExecution(exchange, orderId, CLOSE_CONFIRM_RETRIES, CLOSE_CONFIRM_INTERVAL):
        detail += " (指値未約定 → 成行フォールバック)"
        try:
          exchange.cancelOrder(orderId)
        except Exception:
          pass
        exchange.orderMarket(symbol, orderSide, size)
    except Exception as e:
      # 指値も成行も失敗 → 最終手段として成行を試行
      detail += f" (決済注文失敗: {e} → 成行リトライ)"
      try:
        exchange.orderMarket(symbol, orderSide, size)
      except Exception as e2:
        detail += f" (成行も失敗: {e2})"
        return "ERROR", detail

  state["totalTrades"] += 1
  if pnl > 0:
    state["wins"] += 1
  elif pnl < 0:
    state["losses"] += 1
  state["totalPnl"] += pnl
  state["position"] = "none"
  state["entryPrice"] = 0
  state["entrySize"] = 0
  state["stopOrderId"] = None
  state["stopPrice"] = 0
  state["trades"].append({
    "datetime": datetime.now(JST).isoformat(),
    "type": f"close_{side}", "price": orderPrice, "size": size, "pnl": pnl, "dryRun": dryRun,
  })

  return "SELL" if side == "long" else "BUY", detail


def runCycle(config: dict, dryRun: bool = True) -> list[dict]:
  """全戦略を1サイクル実行"""
  traderCfg = config.get("trader", {})
  symbol = traderCfg.get("symbol", "BTC")
  strategiesCfg = traderCfg.get("strategies", [])

  if not strategiesCfg:
    print("  戦略が設定されていません (config.yaml trader.strategies)")
    return []

  exchange = GmoExchange()
  now = datetime.now(JST)

  print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Cycle start")
  print(f"  symbol: {symbol}  strategies: {len(strategiesCfg)}  dry_run: {dryRun}")

  # 価格取得
  ticker = exchange.getTicker(symbol)
  price = ticker["last"]
  print(f"  price: {price:,.0f}  bid: {ticker['bid']:,.0f}  ask: {ticker['ask']:,.0f}")

  # 残高
  if dryRun:
    # config.yaml の trader.dry_run_balance で設定可能（未設定時は100,000円）
    dryBalance = traderCfg.get("dry_run_balance", 100_000)
    totalEquity = dryBalance
    availableJpy = dryBalance
    print(f"  balance (dry): {totalEquity:,.0f} JPY")
  else:
    balance = exchange.getBalance()
    balJpy = balance.get("JPY", {}).get("available", 0)
    balBtc = balance.get("BTC", {}).get("available", 0)
    totalEquity = balJpy + balBtc * price
    availableJpy = balJpy
    print(f"  balance: {balJpy:,.0f} JPY + {balBtc} BTC = {totalEquity:,.0f}")

  # リスクマネージャー（サイクル全体で共有）
  riskCfg = traderCfg.get("risk", {})
  riskMgr = RiskManager({**riskCfg, "capital_ratio": 0.9})
  riskMgr.setDailyStart(totalEquity)

  # レジーム判定 + 動的weight調整
  dynamicCfg = traderCfg.get("dynamic_weight", {})
  regime = "range"
  if dynamicCfg.get("enabled", False):
    trendMaPeriod = dynamicCfg.get("trend_ma_period", 50)
    threshold = dynamicCfg.get("threshold", 2.0)
    sma50Dev = None
    try:
      import strategies
      from strategies.registry import getStrategy
      s = getStrategy("bb")
      data = s.fetchData(symbol=f"{symbol}USDT", interval="1d", years=1)
      if len(data) >= trendMaPeriod:
        trendMa = data["close"].rolling(trendMaPeriod).mean().iloc[-1]
        regime = detectRegime(price, trendMa, threshold)
        sma50Dev = (price - trendMa) / trendMa * 100 if trendMa else None
    except Exception as e:
      print(f"  [regime] 判定失敗、rangeで続行: {e}")

    regimeWeights = dynamicCfg.get("regime_weights", DEFAULT_REGIME_WEIGHTS)

    # ファンダスコアによる補正 (Early Transition + Boost)
    fundaScore = None
    fundaWeightOverride = None
    fundaCfg = dynamicCfg.get("funda", {})
    if fundaCfg.get("enabled", False):
      try:
        from signals.collectors.macro_collector import (
          get_gold_history, get_tnx_history, get_fng_history,
        )
        from signals.scorer import calcFundaScore
        goldHist = get_gold_history(days=fundaCfg.get("gold_days", 80))
        tnxHist = get_tnx_history(days=fundaCfg.get("tnx_days", 35))
        fngHist = get_fng_history(days=fundaCfg.get("fng_days", 40))
        fundaScore = calcFundaScore(goldHist, tnxHist, fngHist)
        origRegime = regime
        regime, fundaWeightOverride = adjustRegimeByFunda(
          regime, sma50Dev, fundaScore,
          upZone=fundaCfg.get("up_zone", 5.0),
          downZone=fundaCfg.get("down_zone", -10.0),
          fundaThr=fundaCfg.get("threshold", 0.3),
          boostThr=fundaCfg.get("boost_threshold", 0.5),
        )
        adjStr = ""
        if regime != origRegime:
          adjStr = f" (funda: {origRegime}->{regime})"
        elif fundaWeightOverride:
          adjStr = " (funda: BOOST)"
        print(f"  funda_score: {fundaScore:+.2f}{adjStr}")
      except Exception as e:
        print(f"  [funda] 取得失敗、テクニカルのみで続行: {e}")

    print(f"  regime: {regime}  dynamic_weight: ON")
  else:
    regimeWeights = None
    print(f"  dynamic_weight: OFF")

  # 各戦略を実行
  results = []
  for sCfg in strategiesCfg:
    # 動的weight適用（ファンダブースト時はそちらを優先）
    if regimeWeights:
      if fundaWeightOverride:
        sCfg = {**sCfg, "weight": fundaWeightOverride.get(sCfg["name"], 0)}
      else:
        sCfg = {**sCfg, "weight": _getRegimeWeight(sCfg["name"], regime, regimeWeights)}
    elif "weight" not in sCfg:
      sCfg = {**sCfg, "weight": 50}  # OFFの時のフォールバック
    try:
      r = _runStrategy(sCfg, exchange, ticker, price, totalEquity, availableJpy, config, dryRun, riskMgr)
      results.append(r)
    except Exception as e:
      print(f"  [{sCfg['name']}] ERROR: {e}")
      results.append({"action": "ERROR", "detail": str(e)})

  # サマリー
  print(f"\n  === Summary ===")
  for sCfg in strategiesCfg:
    state = _loadState(sCfg["name"])
    nt = state.get("totalTrades", 0)
    wr = state["wins"] / nt * 100 if nt > 0 else 0
    print(f"  {sCfg['name']:<10s}  pos:{state.get('position','?'):<6s}  "
          f"pnl:{state.get('totalPnl',0):>+10,.0f}  wr:{wr:.0f}% ({nt})")

  return results
