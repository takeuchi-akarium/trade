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
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, send_from_directory, jsonify

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
  with open(path, "r", encoding="utf-8") as f:
    return json.load(f)


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


if __name__ == "__main__":
  print("Dashboard: http://localhost:5000")
  app.run(debug=True, port=5000)
