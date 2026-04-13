"""
ファンダスコア閾値感度分析
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta

FUNDA_THRS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
BOOST_THRS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
UP_ZONE    = 5.0
DOWN_ZONE  = -10.0

def fetch_btc_daily(days=1000):
  print(f"[1/4] BTC日足取得中 ({days}日)...")
  url = "https://api.binance.com/api/v3/klines"
  all_candles = []
  end_ms = int(datetime.utcnow().timestamp() * 1000)
  remaining = days
  while remaining > 0:
    limit = min(1000, remaining)
    params = {"symbol": "BTCUSDT", "interval": "1d", "endTime": end_ms, "limit": limit}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    candles = resp.json()
    if not candles:
      break
    all_candles = candles + all_candles
    end_ms = candles[0][0] - 1
    remaining -= len(candles)
  cols = ["ts","open","high","low","close","vol","close_ts","qvol","ntrades","taker_base","taker_quote","_"]
  df = pd.DataFrame(all_candles, columns=cols)
  df["date"]  = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
  for col in ["close","open","high","low"]:
    df[col] = df[col].astype(float)
  df = df[["date","open","high","low","close"]].set_index("date").sort_index()
  print(f"  BTC: {len(df)}行  {df.index[0].date()} ~ {df.index[-1].date()}")
  return df


def fetch_gold_tnx(years=5):
  print(f"[2/4] Gold/TNX取得中 (yfinance {years}年)...")
  end   = datetime.today()
  start = end - timedelta(days=365 * years + 30)
  gc    = yf.download("GC=F",  start=start, end=end, interval="1d", progress=False, auto_adjust=True)
  tnx   = yf.download("^TNX",  start=start, end=end, interval="1d", progress=False, auto_adjust=True)
  gold_close = gc["Close"].squeeze().dropna()
  tnx_close  = tnx["Close"].squeeze().dropna()
  gold_close.index = pd.to_datetime(gold_close.index).normalize()
  tnx_close.index  = pd.to_datetime(tnx_close.index).normalize()
  print(f"  Gold: {len(gold_close)}行  {gold_close.index[0].date()} ~ {gold_close.index[-1].date()}")
  print(f"  TNX : {len(tnx_close)}行  {tnx_close.index[0].date()} ~ {tnx_close.index[-1].date()}")
  return gold_close, tnx_close


def fetch_fng(days=1100):
  print(f"[3/4] FnG取得中 ({days}日)...")
  resp = requests.get(
    "https://api.alternative.me/fng/",
    params={"limit": days},
    timeout=30,
  )
  resp.raise_for_status()
  data   = resp.json()["data"]
  dates  = pd.to_datetime([int(d["timestamp"]) for d in data], unit="s").normalize()
  values = [int(d["value"]) for d in data]
  s = pd.Series(values, index=dates, name="fng").sort_index()
  print(f"  FnG: {len(s)}行  {s.index[0].date()} ~ {s.index[-1].date()}")
  return s


def calc_rolling_funda_scores(btc, gold, tnx, fng,
                               gold_days=80, tnx_days=35, fng_days=40, window=90):
  from signals.scorer import calcFundaScore
  print(f"[4/4] ファンダスコアをローリング計算中...")
  scores = {}
  for date in btc.index:
    g_hist = gold[gold.index <= date].tail(gold_days).tolist()
    t_hist = tnx[tnx.index <= date].tail(tnx_days).tolist()
    f_hist = fng[fng.index <= date].tail(fng_days).tolist()
    score  = calcFundaScore(g_hist, t_hist, f_hist, window=window)
    scores[date] = score
  s = pd.Series(scores, name="funda_score")
  valid = s.dropna()
  print(f"  スコア計算完了: {len(valid)}日分")
  print(f"  mean={valid.mean():.3f}  std={valid.std():.3f}  min={valid.min():.3f}  max={valid.max():.3f}")
  return s


def add_regime_columns(btc):
  from trader.engine import detectRegime as _det
  df = btc.copy()
  df["sma50"]    = df["close"].rolling(50).mean()
  df["sma50dev"] = (df["close"] - df["sma50"]) / df["sma50"] * 100
  regimes = []
  for _, row in df.iterrows():
    if pd.isna(row["sma50"]):
      regimes.append("range")
    else:
      regimes.append(_det(row["close"], row["sma50"]))
  df["regime"] = regimes
  return df

def grid_search(df):
  df = df.copy()
  df["ret30"] = df["close"].pct_change(30).shift(-30) * 100
  rows = []
  for ft in FUNDA_THRS:
    for bt in BOOST_THRS:
      et_up   = []
      et_down = []
      bo_up   = []
      bo_rng  = []
      for date, row in df.iterrows():
        score  = row.get("funda_score")
        regime = row.get("regime")
        dev    = row.get("sma50dev")
        if pd.isna(score) or pd.isna(dev):
          continue
        if dev > 0 and dev < UP_ZONE and score < -ft:
          et_up.append(date)
        if dev < 0 and dev > DOWN_ZONE and score > ft:
          et_down.append(date)
        if regime == "uptrend" and score > bt:
          bo_up.append(date)
        if regime == "range" and score > bt:
          bo_rng.append(date)
      def avg30(dates):
        if not dates:
          return float("nan")
        rets = df.loc[df.index.isin(dates), "ret30"].dropna()
        return float(rets.mean()) if len(rets) > 0 else float("nan")
      rows.append({
        "fundaThr":        ft,
        "boostThr":        bt,
        "et_up_count":     len(et_up),
        "et_down_count":   len(et_down),
        "boost_up_count":  len(bo_up),
        "boost_rng_count": len(bo_rng),
        "et_up_ret30":     avg30(et_up),
        "et_down_ret30":   avg30(et_down),
        "boost_up_ret30":  avg30(bo_up),
        "boost_rng_ret30": avg30(bo_rng),
      })
  return pd.DataFrame(rows)

def run_scenario_comparison(top_params):
  from simulator.scenario import SCENARIOS, REGIME_WEIGHTS
  from strategies.scalping.backtest import runBacktest, runBacktestLongShort
  import strategies
  from strategies.registry import getStrategy
  from trader.engine import adjustRegimeByFunda

  pats = [
    {"label": "テクニカルのみ", "use_funda": False, "ft": None, "bt": None},
    {"label": "旧閾値(0.3/0.5)",  "use_funda": True,  "ft": 0.3,  "bt": 0.5},
  ]
  for p in top_params:
    pats.append({
      "label":     "新候補(%.1f/%.1f)" % (p["fundaThr"], p["boostThr"]),
      "use_funda": True,
      "ft":        p["fundaThr"],
      "bt":        p["boostThr"],
    })

  initial_capital = 100_000
  fee_pct         = 0.1
  trend_ma_period = 50
  result_rows     = []

  for sKey, sInfo in SCENARIOS.items():
    data    = sInfo["fn"]()
    trendMa = data["close"].rolling(trend_ma_period).mean()

    bbSt   = getStrategy("bb")
    emaSt  = getStrategy("ema_don")
    bbLsSt = getStrategy("bb_ls")

    dfBb   = bbSt.generateSignals(data.copy())
    dfEma  = emaSt.generateSignals(data.copy(), short=10, long=50)
    dfBbLs = bbLsSt.generateSignals(data.copy())

    _, eqBb   = runBacktest(dfBb,  initial_capital, fee_pct / 100)
    _, eqEma  = runBacktest(dfEma, initial_capital, fee_pct / 100)
    _, eqBbLs = runBacktestLongShort(dfBbLs, initial_capital, fee_pct / 100, stopLossPct=5.0)

    retBb   = eqBb.pct_change().fillna(0)
    retEma  = eqEma.pct_change().fillna(0)
    retBbLs = eqBbLs.pct_change().fillna(0)

    rng_fs         = np.random.RandomState(42)
    funda_scores_s = rng_fs.normal(0, 0.81, len(data))
    sma50devs      = ((data["close"] - trendMa) / trendMa * 100).values

    for pat in pats:
      equity      = initial_capital
      eq_list     = []
      prev_regime = None

      for i in range(len(data)):
        close = data["close"].iloc[i]
        ma    = trendMa.iloc[i]
        if np.isnan(ma):
          regime = "range"
        elif close > ma * 1.02:
          regime = "uptrend"
        elif close < ma * 0.98:
          regime = "downtrend"
        else:
          regime = "range"

        weight_override = None
        if pat["use_funda"]:
          dev    = float(sma50devs[i]) if not np.isnan(sma50devs[i]) else 0.0
          fs     = funda_scores_s[i]
          regime, weight_override = adjustRegimeByFunda(
            regime, dev, fs,
            upZone=UP_ZONE, downZone=DOWN_ZONE,
            fundaThr=pat["ft"], boostThr=pat["bt"],
          )

        if weight_override:
          wBb   = weight_override.get("bb",      0) / 100
          wEma  = weight_override.get("ema_don", 0) / 100
          wBbLs = weight_override.get("bb_ls",   0) / 100
        else:
          rw = REGIME_WEIGHTS.get(regime, (0, 0, 0))
          wBb, wEma, wBbLs = rw

        if prev_regime is not None and regime != prev_regime:
          equity -= equity * fee_pct / 100 * 2

        rBb   = float(retBb.iloc[i])   if i < len(retBb)   else 0.0
        rEma  = float(retEma.iloc[i])  if i < len(retEma)  else 0.0
        rBbLs = float(retBbLs.iloc[i]) if i < len(retBbLs) else 0.0
        port  = wBb * rBb + wEma * rEma + wBbLs * rBbLs

        equity *= (1 + port)
        eq_list.append(equity)
        prev_regime = regime

      eq_s      = pd.Series(eq_list, index=data.index)
      total_ret = (eq_list[-1] - initial_capital) / initial_capital * 100
      peak      = eq_s.expanding().max()
      mdd       = ((eq_s - peak) / peak * 100).min()

      result_rows.append({
        "scenario":    sInfo["name"],
        "scenarioKey": sKey,
        "pattern":     pat["label"],
        "totalReturn": total_ret,
        "mdd":         mdd,
        "probability": sInfo["probability"],
      })

  return pd.DataFrame(result_rows)
