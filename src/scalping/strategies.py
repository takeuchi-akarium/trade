"""
短期売買戦略モジュール

4つの戦略を共通インターフェースで提供。
calcSignals(df) → df に "signal" 列を追加 (+1=買い, -1=売り, 0=様子見)
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------

def _crossover(series: pd.Series, threshold: float = 0) -> pd.Series:
  """seriesがthresholdを上抜けた瞬間を検出"""
  above = series > threshold
  return above & ~above.shift(1, fill_value=False)


def _crossunder(series: pd.Series, threshold: float = 0) -> pd.Series:
  """seriesがthresholdを下抜けた瞬間を検出"""
  below = series < threshold
  return below & ~below.shift(1, fill_value=False)


# ---------------------------------------------------------------------------
# RSI 逆張り
# ---------------------------------------------------------------------------

def calcRsi(df: pd.DataFrame,
            period: int = 14,
            oversold: float = 30,
            overbought: float = 70) -> pd.DataFrame:
  df = df.copy()
  delta = df["close"].diff()
  gain = delta.clip(lower=0)
  loss = -delta.clip(upper=0)

  avgGain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
  avgLoss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

  rs = avgGain / avgLoss.replace(0, np.nan)
  df["rsi"] = 100 - 100 / (1 + rs)

  df["signal"] = 0
  df.loc[_crossunder(df["rsi"], oversold), "signal"] = 1   # 売られすぎから反発 → 買い
  df.loc[_crossover(df["rsi"], overbought), "signal"] = -1  # 買われすぎから反落 → 売り
  return df


# ---------------------------------------------------------------------------
# ボリンジャーバンド
# ---------------------------------------------------------------------------

def calcBb(df: pd.DataFrame,
           period: int = 20,
           std: float = 2.0) -> pd.DataFrame:
  df = df.copy()
  df["bb_mid"] = df["close"].rolling(period).mean()
  rolling_std = df["close"].rolling(period).std()
  df["bb_upper"] = df["bb_mid"] + std * rolling_std
  df["bb_lower"] = df["bb_mid"] - std * rolling_std

  df["signal"] = 0
  df.loc[df["close"] <= df["bb_lower"], "signal"] = 1   # 下バンド割れ → 買い
  df.loc[df["close"] >= df["bb_upper"], "signal"] = -1  # 上バンド割れ → 売り
  return df


# ---------------------------------------------------------------------------
# EMA クロス
# ---------------------------------------------------------------------------

def calcEma(df: pd.DataFrame,
            short: int = 5,
            long: int = 20) -> pd.DataFrame:
  df = df.copy()
  df["ema_short"] = df["close"].ewm(span=short, adjust=False).mean()
  df["ema_long"] = df["close"].ewm(span=long, adjust=False).mean()

  diff = df["ema_short"] - df["ema_long"]
  df["signal"] = 0
  df.loc[_crossover(diff), "signal"] = 1   # ゴールデンクロス → 買い
  df.loc[_crossunder(diff), "signal"] = -1  # デッドクロス → 売り
  return df


# ---------------------------------------------------------------------------
# VWAP 乖離
# ---------------------------------------------------------------------------

def calcVwap(df: pd.DataFrame,
             threshold: float = 1.0) -> pd.DataFrame:
  """
  VWAP乖離率で平均回帰を狙う。
  volumeが無い場合はSMA代替(period=20)でフォールバック。
  """
  df = df.copy()

  if "volume" in df.columns and df["volume"].sum() > 0:
    cumVol = df["volume"].cumsum()
    cumTp = (df["close"] * df["volume"]).cumsum()
    df["vwap"] = cumTp / cumVol.replace(0, np.nan)
  else:
    # volume無し → 20期間SMAで代替
    df["vwap"] = df["close"].rolling(20).mean()

  df["vwap_dev"] = (df["close"] - df["vwap"]) / df["vwap"] * 100  # 乖離率%

  df["signal"] = 0
  df.loc[df["vwap_dev"] <= -threshold, "signal"] = 1   # VWAP大幅下方乖離 → 買い
  df.loc[df["vwap_dev"] >= threshold, "signal"] = -1  # VWAP大幅上方乖離 → 売り
  return df


# ---------------------------------------------------------------------------
# 戦略レジストリ
# ---------------------------------------------------------------------------

STRATEGIES = {
  "rsi": {"fn": calcRsi, "name": "RSI逆張り", "defaults": {"period": 14, "oversold": 30, "overbought": 70}},
  "bb":  {"fn": calcBb,  "name": "ボリンジャーバンド", "defaults": {"period": 20, "std": 2.0}},
  "ema": {"fn": calcEma, "name": "EMAクロス", "defaults": {"short": 5, "long": 20}},
  "vwap": {"fn": calcVwap, "name": "VWAP乖離", "defaults": {"threshold": 1.0}},
}


def calcSignals(df: pd.DataFrame, strategyKey: str, **kwargs) -> pd.DataFrame:
  """指定戦略のシグナルを計算"""
  entry = STRATEGIES[strategyKey]
  params = {**entry["defaults"], **kwargs}
  return entry["fn"](df, **params)


def calcCombinedSignals(df: pd.DataFrame, strategyKeys: list[str], **kwargs) -> pd.DataFrame:
  """複数戦略のAND合成。全戦略が同方向のときのみシグナル発生"""
  signals = []
  resultDf = df.copy()

  for key in strategyKeys:
    sDf = calcSignals(df, key, **kwargs)
    signals.append(sDf["signal"])

  combined = pd.concat(signals, axis=1)
  resultDf["signal"] = 0

  # 全戦略が+1 → 買い
  allBuy = (combined == 1).all(axis=1)
  resultDf.loc[allBuy, "signal"] = 1

  # いずれかの戦略が-1 → 売り（1つでも売りシグナルが出たら決済）
  anySell = (combined == -1).any(axis=1)
  resultDf.loc[anySell, "signal"] = -1

  return resultDf
