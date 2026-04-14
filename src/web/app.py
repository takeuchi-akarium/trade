"""
トレードダッシュボード Web アプリ

ローカル: python src/web/app.py → http://localhost:5000
ページを開くとライブデータ(マクロ/BTC)を取得し、キャッシュする。
リードラグ・シグナルログ・ペーパー状態はファイルから読み取る。

WEB公開時の設計:
  - このFlaskアプリをPaaS(Render, Railway等)にデプロイ
  - ファイル依存のデータ(signal_log, position_history)はDB or GH APIから取得に切替
  - ライブデータ(マクロ/BTC)は現状のまま(API→キャッシュ)で動作する
  - 環境変数: FLASK_ENV=production, SECRET_KEY, 各APIキー
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, send_from_directory, jsonify, request as flaskRequest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

app = Flask(__name__)

DATA_DIR = ROOT / "data"
SIGNALS_DIR = DATA_DIR / "signals"
LEADLAG_DIR = DATA_DIR / "leadlag"

# ── ライブデータキャッシュ (TTL: 5分) ──

CACHE = {}
CACHE_TTL = 300  # seconds


def cached(key, fetcher):
  """キャッシュがTTL内なら返す、なければfetcherを実行して格納"""
  now = time.time()
  if key in CACHE and now - CACHE[key]["t"] < CACHE_TTL:
    return CACHE[key]["data"]
  try:
    data = fetcher()
    CACHE[key] = {"data": data, "t": now}
    return data
  except Exception:
    # 取得失敗時は古いキャッシュがあればそれを返す
    if key in CACHE:
      return CACHE[key]["data"]
    return None


# ── ライブ取得: マクロシグナル ──

def fetchLiveMacro():
  """Fear&Greed + VIX をリアルタイム取得してスコアリング"""
  from signals.aggregator import collect_and_score, to_signal
  from common.config_loader import load_config

  config = load_config()
  sigCfg = config.get("signal", {})
  result = collect_and_score(sigCfg.get("weights"))
  total = result["total"]
  signal = to_signal(
    total,
    buy_threshold=sigCfg.get("buy_threshold", 30),
    sell_threshold=sigCfg.get("sell_threshold", -30),
  )
  return {
    "signal": signal,
    "total": total,
    "scores": result["scores"],
    "details": result["details"],
    "updated_at": datetime.now().isoformat(),
  }


# ── ライブ取得: BTC価格 ──

def fetchLiveBtc():
  """CoinGecko APIからBTC現在価格を取得"""
  resp = requests.get(
    "https://api.coingecko.com/api/v3/coins/bitcoin",
    params={
      "localization": "false",
      "tickers": "false",
      "community_data": "false",
      "developer_data": "false",
    },
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=10,
  )
  resp.raise_for_status()
  md = resp.json().get("market_data", {})
  return {
    "price": md.get("current_price", {}).get("usd", 0),
    "change_24h": md.get("price_change_percentage_24h", 0),
    "high_24h": md.get("high_24h", {}).get("usd", 0),
    "low_24h": md.get("low_24h", {}).get("usd", 0),
  }


# ── ファイル読み取り ──

def loadJson(path):
  if not path.exists():
    return None
  try:
    with open(path, "r", encoding="utf-8") as f:
      return json.load(f)
  except (json.JSONDecodeError, OSError):
    return None


def loadSignalLog(limit=50):
  path = SIGNALS_DIR / "signal_log.tsv"
  if not path.exists():
    return []

  with open(path, "r", encoding="utf-8") as f:
    text = f.read()

  entries = []
  current = None
  for line in text.strip().split("\n"):
    if line and len(line) > 10 and line[0] == "2" and "T" in line[:25]:
      if current:
        entries.append(current)
      parts = line.split("\t", 1)
      ts = parts[0].strip()
      body = parts[1].strip() if len(parts) > 1 else ""
      current = {"timestamp": ts, "body": body, "details": []}
    elif current:
      current["details"].append(line.strip())

  if current:
    entries.append(current)

  entries.reverse()
  return entries[:limit]


def loadBtcPriceHistory(days=30):
  path = DATA_DIR / "btc_1d.csv"
  if not path.exists():
    return []

  import csv
  rows = []
  with open(path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
      rows.append(row)

  recent = rows[-days:]
  return [
    {
      "date": row.get("datetime", row.get("date", "")),
      "close": float(row.get("close", 0)),
    }
    for row in recent
  ]


# ── Routes ──

@app.route("/")
def index():
  return send_from_directory(ROOT / "docs", "index.html")


@app.route("/api/dashboard")
def apiDashboard():
  """ダッシュボード全データ。マクロとBTCはライブ取得(5分キャッシュ)"""
  # ライブ: マクロシグナル (失敗時はファイルにフォールバック)
  macroSignal = cached("macro", fetchLiveMacro)
  if macroSignal is None:
    macroSignal = loadJson(SIGNALS_DIR / "latest_signal.json")

  # ライブ: BTC現在価格
  liveBtc = cached("btc", fetchLiveBtc)

  # ファイル: BTC価格推移 (日足チャート用)
  btcHistory = loadBtcPriceHistory(60)

  # ファイル: ペーパートレード状態
  paperState = loadJson(DATA_DIR / "paper_state.json")

  # ファイル: リードラグポジション
  positionHistory = loadJson(LEADLAG_DIR / "position_history.json")
  latestPosition = None
  if positionHistory and len(positionHistory) > 0:
    latestPosition = positionHistory[-1]

  # ファイル: シグナルログ
  signalLog = loadSignalLog(30)

  return jsonify({
    "macroSignal": macroSignal,
    "liveBtc": liveBtc,
    "paperState": paperState,
    "latestPosition": latestPosition,
    "signalLog": signalLog,
    "btcHistory": btcHistory,
  })


# ── Simulations ──

SIM_DIR = DATA_DIR / "simulations"
SIM_LIVE_DIR = SIM_DIR / "live"


@app.route("/strategy")
def strategy():
  return send_from_directory(ROOT / "docs", "strategy.html")


@app.route("/simulations")
def simulations():
  return send_from_directory(ROOT / "docs", "simulations.html")


@app.route("/api/simulations")
def apiSimulations():
  """保存済みバックテスト結果の一覧 + ライブシミュレーション状態"""
  backtests = []
  if SIM_DIR.exists():
    for f in sorted(SIM_DIR.glob("*.json"), reverse=True):
      try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data["_filename"] = f.name
        backtests.append(data)
      except Exception:
        pass

  liveStates = []
  if SIM_LIVE_DIR.exists():
    for f in SIM_LIVE_DIR.glob("*.json"):
      try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data["_filename"] = f.name
        liveStates.append(data)
      except Exception:
        pass

  return jsonify({
    "backtests": backtests,
    "live": liveStates,
  })


@app.route("/api/simulations/<filename>")
def apiSimulationDetail(filename):
  """個別バックテスト結果の詳細"""
  path = (SIM_DIR / filename).resolve()
  if not path.is_relative_to(SIM_DIR.resolve()):
    return jsonify({"error": "not found"}), 404
  if not path.exists() or not path.suffix == ".json":
    return jsonify({"error": "not found"}), 404
  data = json.loads(path.read_text(encoding="utf-8"))
  return jsonify(data)


# ── Trader ──

TRADER_DIR = DATA_DIR / "trader"


@app.route("/trader")
def trader():
  return send_from_directory(ROOT / "docs", "trader.html")


@app.route("/api/trader")
def apiTrader():
  """全戦略のトレード実績"""
  strategies = []
  if TRADER_DIR.exists():
    for f in sorted(TRADER_DIR.glob("state_*.json")):
      try:
        data = json.loads(f.read_text(encoding="utf-8"))
        strategies.append(data)
      except Exception:
        pass

  # 合計
  totalPnl = sum(s.get("totalPnl", 0) for s in strategies)
  totalTrades = sum(s.get("totalTrades", 0) for s in strategies)
  totalWins = sum(s.get("wins", 0) for s in strategies)

  return jsonify({
    "strategies": strategies,
    "summary": {
      "totalPnl": totalPnl,
      "totalTrades": totalTrades,
      "winRate": totalWins / totalTrades * 100 if totalTrades > 0 else 0,
    },
  })


@app.route("/api/trader/funda")
def apiTraderFunda():
  """ファンダスコアとレジーム判定の現在状態"""
  try:
    from signals.collectors.macro_collector import (
      get_gold, get_tnx, get_fear_greed,
      get_gold_history, get_tnx_history, get_fng_history,
    )
    from signals.scorer import calcFundaScore

    goldHist = get_gold_history(days=80)
    tnxHist = get_tnx_history(days=35)
    fngHist = get_fng_history(days=40)
    fundaScore = calcFundaScore(goldHist, tnxHist, fngHist)

    gold = get_gold()
    tnx = get_tnx()
    fng = get_fear_greed()

    return jsonify({
      "fundaScore": round(fundaScore, 3),
      "indicators": {
        "gold": {"price": gold, "history_days": len(goldHist)},
        "tnx": {"value": tnx, "history_days": len(tnxHist)},
        "fng": {"value": fng["value"], "label": fng["label"], "history_days": len(fngHist)},
      },
      "updated_at": datetime.now().isoformat(),
    })
  except Exception as e:
    return jsonify({"error": str(e)}), 500


# ── Gap Scan ──

@app.route("/gap-scan")
def gapScan():
  return send_from_directory(ROOT / "docs", "gap_scan.html")


@app.route("/api/gap-scan")
def apiGapScan():
  """ギャップスキャン結果をJSON返却 (5分キャッシュ、refresh=1でクリア)"""
  if flaskRequest.args.get("refresh") == "1" and "gap_scan" in CACHE:
    del CACHE["gap_scan"]

  def _fetch():
    from strategies.jp_stock.gap_scanner import generateMorningReport
    return generateMorningReport()

  report = cached("gap_scan", _fetch)
  if report is None:
    return jsonify({"error": "スキャン失敗"}), 500
  return jsonify(report)


# ── Trade Journal ──

JOURNAL_DIR = DATA_DIR / "trade_journal"


@app.route("/trade-journal")
def tradeJournal():
  return send_from_directory(ROOT / "docs", "trade_journal.html")


@app.route("/api/trade-journal")
def apiTradeJournal():
  """判断記録一覧 + 統計"""
  from trade_journal import loadEntries, calcStats
  return jsonify({
    "entries": loadEntries(),
    "stats": calcStats(),
  })


@app.route("/api/trade-journal", methods=["POST"])
def apiTradeJournalAdd():
  """新規エントリ追加"""
  from trade_journal import addEntry
  data = flaskRequest.get_json()
  entry = addEntry(
    ticker=data.get("ticker", ""),
    direction=data.get("direction", "long"),
    name=data.get("name", ""),
    preMarket=data.get("pre_market"),
    technicals=data.get("technicals"),
    news=data.get("news"),
    reasoning=data.get("reasoning", ""),
  )
  return jsonify(entry), 201


@app.route("/api/trade-journal/screenshot/<path:filename>")
def apiTradeJournalScreenshot(filename):
  """板スクリーンショット配信"""
  screenshotDir = JOURNAL_DIR / "screenshots"
  resolved = (screenshotDir / filename).resolve()
  if not resolved.is_relative_to(screenshotDir.resolve()):
    return jsonify({"error": "not found"}), 404
  return send_from_directory(screenshotDir, filename)


# ── DART 手動チェック ──

DART_LAST_CHECK = DATA_DIR / "trader" / "last_dart_check.json"


@app.route("/api/dart/last")
def apiDartLast():
  """前回のチェック結果を返す"""
  data = loadJson(DART_LAST_CHECK)
  if data is None:
    return jsonify({"empty": True})
  return jsonify(data)


@app.route("/api/dart/check")
def apiDartCheck():
  """DART分析のみ実行（注文は出さない）。結果をファイルに保存"""
  try:
    from common.config_loader import load_config
    from trader.engine import checkDart
    config = load_config()
    result = checkDart(config)
    # 保存
    DART_LAST_CHECK.parent.mkdir(parents=True, exist_ok=True)
    DART_LAST_CHECK.write_text(
      json.dumps(result, indent=2, ensure_ascii=False, default=str),
      encoding="utf-8",
    )
    return jsonify(result)
  except Exception as e:
    return jsonify({"error": str(e)}), 500


@app.route("/api/dart/execute", methods=["POST"])
def apiDartExecute():
  """DART注文を実行"""
  try:
    from common.config_loader import load_config
    from trader.engine import runCycle
    config = load_config()
    dryRun = config.get("trader", {}).get("dry_run", True)
    results = runCycle(config, dryRun=dryRun)
    return jsonify({"results": results, "dryRun": dryRun})
  except Exception as e:
    return jsonify({"error": str(e)}), 500


@app.route("/api/dart/mode")
def apiDartMode():
  """現在のdry_runモードを返す"""
  from common.config_loader import load_config
  config = load_config()
  dryRun = config.get("trader", {}).get("dry_run", True)
  return jsonify({"dryRun": dryRun})


@app.route("/api/dart/mode", methods=["POST"])
def apiDartModeToggle():
  """dry_runモードを切り替える（config.yamlを書き換え）"""
  import re
  configPath = ROOT / "config.yaml"
  text = configPath.read_text(encoding="utf-8")

  # 現在値を検出
  match = re.search(r"^(\s*dry_run:\s*)(true|false)", text, re.MULTILINE)
  if not match:
    return jsonify({"error": "dry_run not found in config.yaml"}), 500

  current = match.group(2) == "true"
  newVal = not current
  newText = text[:match.start(2)] + str(newVal).lower() + text[match.end(2):]
  configPath.write_text(newText, encoding="utf-8")

  return jsonify({"dryRun": newVal})


# ── Manual Simulation (手動売買シミュレーション) ──

import threading

MANUAL_SIM_FILE = TRADER_DIR / "manual_sim.json"
_msLock = threading.Lock()

# 初期残高は起動時に1回だけ読み込む
def _loadInitBalance():
  from common.config_loader import load_config
  config = load_config()
  return config.get("trader", {}).get("dry_run_balance", 50000)

_MS_INIT_BALANCE = _loadInitBalance()


def loadManualSim():
  """手動シミュレーション状態を読み込み。なければ初期状態を返す"""
  default = {
    "initialBalance": _MS_INIT_BALANCE,
    "balance": _MS_INIT_BALANCE,
    "positions": [],
    "closedTrades": [],
  }
  data = loadJson(MANUAL_SIM_FILE)
  if data is None:
    return default
  return data


def saveManualSim(data):
  """手動シミュレーション状態を保存"""
  MANUAL_SIM_FILE.parent.mkdir(parents=True, exist_ok=True)
  MANUAL_SIM_FILE.write_text(
    json.dumps(data, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8",
  )


@app.route("/api/manual-sim")
def apiManualSim():
  """手動シミュレーション状態を返す"""
  data = loadManualSim()
  return jsonify(data)


@app.route("/api/manual-sim/buy", methods=["POST"])
def apiManualSimBuy():
  """手動ロング（買い）"""
  body = flaskRequest.get_json(silent=True) or {}
  try:
    size = float(body.get("size", 0))
    price = float(body.get("price", 0))
  except (ValueError, TypeError):
    return jsonify({"error": "size と price は数値が必要です"}), 400
  if size <= 0 or price <= 0:
    return jsonify({"error": "size と price は正の値が必要です"}), 400

  import uuid
  with _msLock:
    data = loadManualSim()
    cost = price * size
    if cost > data["balance"]:
      return jsonify({"error": f"残高不足: 必要 {cost:.0f}円 / 残高 {data['balance']:.0f}円"}), 400

    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    posId = uuid.uuid4().hex[:12] + "_L"
    data["balance"] -= cost
    data["positions"].append({
      "id": posId,
      "type": "long",
      "price": price,
      "size": size,
      "cost": cost,
      "datetime": now,
    })
    saveManualSim(data)
  return jsonify({"ok": True, "position": data["positions"][-1], "balance": data["balance"]})


@app.route("/api/manual-sim/short", methods=["POST"])
def apiManualSimShort():
  """手動ショート（空売り）"""
  body = flaskRequest.get_json(silent=True) or {}
  try:
    size = float(body.get("size", 0))
    price = float(body.get("price", 0))
  except (ValueError, TypeError):
    return jsonify({"error": "size と price は数値が必要です"}), 400
  if size <= 0 or price <= 0:
    return jsonify({"error": "size と price は正の値が必要です"}), 400

  import uuid
  with _msLock:
    data = loadManualSim()
    # ショートは証拠金として必要額を仮押さえ
    margin = price * size
    if margin > data["balance"]:
      return jsonify({"error": f"証拠金不足: 必要 {margin:.0f}円 / 残高 {data['balance']:.0f}円"}), 400

    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    posId = uuid.uuid4().hex[:12] + "_S"
    data["balance"] -= margin
    data["positions"].append({
      "id": posId,
      "type": "short",
      "price": price,
      "size": size,
      "cost": margin,
      "datetime": now,
    })
    saveManualSim(data)
  return jsonify({"ok": True, "position": data["positions"][-1], "balance": data["balance"]})


@app.route("/api/manual-sim/close", methods=["POST"])
def apiManualSimClose():
  """ポジションを決済"""
  body = flaskRequest.get_json(silent=True) or {}
  posId = str(body.get("id", ""))
  try:
    closePrice = float(body.get("price", 0))
  except (ValueError, TypeError):
    return jsonify({"error": "price は数値が必要です"}), 400
  if not posId or closePrice <= 0:
    return jsonify({"error": "id と price が必要です"}), 400

  with _msLock:
    data = loadManualSim()
    pos = None
    posIdx = -1
    for i, p in enumerate(data["positions"]):
      if p["id"] == posId:
        pos = p
        posIdx = i
        break
    if pos is None:
      return jsonify({"error": "ポジションが見つかりません"}), 404

    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    if pos["type"] == "long":
      pnl = (closePrice - pos["price"]) * pos["size"]
      returnAmount = closePrice * pos["size"]
    else:  # short
      pnl = (pos["price"] - closePrice) * pos["size"]
      returnAmount = max(0, pos["cost"] + pnl)  # 証拠金以上の損失は0で打ち止め

    data["balance"] += returnAmount
    data["closedTrades"].append({
      "id": pos["id"],
      "type": pos["type"],
      "entryPrice": pos["price"],
      "exitPrice": closePrice,
      "size": pos["size"],
      "pnl": round(pnl),
      "entryDatetime": pos["datetime"],
      "exitDatetime": now,
    })
    data["positions"].pop(posIdx)
    saveManualSim(data)
  return jsonify({"ok": True, "pnl": round(pnl), "balance": data["balance"]})


@app.route("/api/manual-sim/reset", methods=["POST"])
def apiManualSimReset():
  """シミュレーションをリセット"""
  with _msLock:
    data = {
      "initialBalance": _MS_INIT_BALANCE,
      "balance": _MS_INIT_BALANCE,
      "positions": [],
      "closedTrades": [],
    }
    saveManualSim(data)
  return jsonify({"ok": True, "balance": _MS_INIT_BALANCE})


# ── Bench ──

BENCH_DIR = SIM_DIR / "bench"
_benchProcess = {"proc": None, "startedAt": None, "args": None, "cancelled": False}


@app.route("/bench")
def bench():
  return send_from_directory(ROOT / "docs", "bench.html")


@app.route("/api/bench")
def apiBench():
  """保存済みベンチ結果の一覧"""
  results = []
  if BENCH_DIR.exists():
    for f in sorted(BENCH_DIR.glob("*.json"), reverse=True):
      try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data["_filename"] = f.name
        results.append(data)
      except Exception:
        pass
  return jsonify({"results": results})


@app.route("/api/bench/<filename>")
def apiBenchDetail(filename):
  """個別ベンチ結果"""
  path = (BENCH_DIR / filename).resolve()
  if not path.is_relative_to(BENCH_DIR.resolve()):
    return jsonify({"error": "not found"}), 404
  if not path.exists() or not path.suffix == ".json":
    return jsonify({"error": "not found"}), 404
  data = json.loads(path.read_text(encoding="utf-8"))
  return jsonify(data)


@app.route("/api/bench/run", methods=["POST"])
def apiBenchRun():
  """ベンチマークをサブプロセスで実行"""
  import subprocess

  # 既に実行中なら拒否
  proc = _benchProcess["proc"]
  if proc is not None and proc.poll() is None:
    return jsonify({"error": "ベンチマーク実行中です", "running": True}), 409

  body = flaskRequest.get_json(silent=True) or {}
  benchType = body.get("type", "backtest")
  strategies = body.get("strategies", "all")
  symbol = body.get("symbol", "BTCUSDT")
  interval = body.get("interval", "1d")
  years = str(body.get("years", 1))
  sl = body.get("sl")
  tp = body.get("tp")

  cmd = [
    sys.executable, str(ROOT / "src" / "simulator" / "runner.py"),
    "bench",
    "--type", benchType,
    "--strategies", strategies,
    "--symbol", symbol,
    "--interval", interval,
    "--years", years,
  ]
  if sl is not None:
    cmd += ["--sl", str(sl)]
  if tp is not None:
    cmd += ["--tp", str(tp)]

  proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    cwd=str(ROOT),
    encoding="utf-8",
    errors="replace",
  )
  _benchProcess["proc"] = proc
  _benchProcess["startedAt"] = datetime.now().isoformat()
  _benchProcess["cancelled"] = False
  _benchProcess["args"] = {
    "type": benchType, "strategies": strategies,
    "symbol": symbol, "interval": interval, "years": int(years),
  }

  return jsonify({"ok": True, "startedAt": _benchProcess["startedAt"], "args": _benchProcess["args"]})


@app.route("/api/bench/status")
def apiBenchStatus():
  """実行中ベンチの状態を確認"""
  proc = _benchProcess["proc"]
  if proc is None:
    return jsonify({"running": False})

  poll = proc.poll()
  if poll is None:
    return jsonify({
      "running": True,
      "startedAt": _benchProcess["startedAt"],
      "args": _benchProcess["args"],
    })

  # 完了: 出力を回収
  stdout = proc.stdout.read() if proc.stdout else ""
  cancelled = _benchProcess["cancelled"]
  _benchProcess["proc"] = None
  return jsonify({
    "running": False,
    "finished": True,
    "returnCode": poll,
    "cancelled": cancelled,
    "output": stdout[-5000:] if len(stdout) > 5000 else stdout,
    "startedAt": _benchProcess["startedAt"],
    "args": _benchProcess["args"],
  })


@app.route("/api/bench/cancel", methods=["POST"])
def apiBenchCancel():
  """実行中のベンチを中止（Windowsではプロセスツリーごとkill）"""
  import subprocess as _sp
  proc = _benchProcess["proc"]
  if proc is None or proc.poll() is not None:
    return jsonify({"ok": False, "error": "実行中のベンチがありません"})

  _benchProcess["cancelled"] = True
  try:
    # Windows: taskkill /F /T でプロセスツリーを強制終了
    _sp.run(
      ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
  except Exception:
    # フォールバック
    proc.kill()
  return jsonify({"ok": True})


if __name__ == "__main__":
  print("Dashboard:    http://localhost:5000")
  print("Simulations:  http://localhost:5000/simulations")
  print("Trader:       http://localhost:5000/trader")
  print("DART:         http://localhost:5000/trader (Manual Control)")
  print("Gap Scan:     http://localhost:5000/gap-scan")
  print("Journal:      http://localhost:5000/trade-journal")
  print("Bench:        http://localhost:5000/bench")
  app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", port=5000)
