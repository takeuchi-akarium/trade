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


def calcBbTrend(df: pd.DataFrame,
                period: int = 20,
                std: float = 2.0,
                trendMaPeriod: int = 200,
                rsiPeriod: int = 14,
                rsiOversold: float = 30,
                rsiOverbought: float = 70,
                lookback: int = 5) -> pd.DataFrame:
  """
  ボリンジャーバンド + トレンドフィルター + RSI反転確認

  エントリー条件（3つ全て満たす）:
    買い: 直近N足でBB下バンド割れ + RSIが売られすぎから回復 + 上昇トレンド
    売り: 直近N足でBB上バンド割れ + RSIが買われすぎから反落 + 下降トレンド
  """
  df = df.copy()

  # BB計算
  df["bb_mid"] = df["close"].rolling(period).mean()
  rollingStd = df["close"].rolling(period).std()
  df["bb_upper"] = df["bb_mid"] + std * rollingStd
  df["bb_lower"] = df["bb_mid"] - std * rollingStd

  # RSI計算
  delta = df["close"].diff()
  gain = delta.clip(lower=0)
  loss = -delta.clip(upper=0)
  avgGain = gain.ewm(alpha=1 / rsiPeriod, min_periods=rsiPeriod, adjust=False).mean()
  avgLoss = loss.ewm(alpha=1 / rsiPeriod, min_periods=rsiPeriod, adjust=False).mean()
  rs = avgGain / avgLoss.replace(0, np.nan)
  df["rsi"] = 100 - 100 / (1 + rs)

  # トレンド判定用の長期MA
  df["trend_ma"] = df["close"].rolling(trendMaPeriod).mean()

  # シグナル生成: BB(直近ゾーン) + RSI反転 + トレンド方向
  df["signal"] = 0

  # 直近N足でBBバンドに触れたか（ゾーン判定）
  bbLowZone = (df["close"] <= df["bb_lower"]).rolling(lookback, min_periods=1).max().astype(bool)
  bbHighZone = (df["close"] >= df["bb_upper"]).rolling(lookback, min_periods=1).max().astype(bool)

  # RSI反転: 売られすぎから「回復」/ 買われすぎから「反落」
  rsiRecovery = _crossover(df["rsi"], rsiOversold)    # RSI30を上抜け = 売られすぎから回復
  rsiReversal = _crossunder(df["rsi"], rsiOverbought)  # RSI70を下抜け = 買われすぎから反落

  # トレンド方向
  upTrend = df["close"] > df["trend_ma"]
  downTrend = df["close"] < df["trend_ma"]

  # 買い: 直近でBB下バンド割れ + RSI回復 + 上昇トレンド
  df.loc[bbLowZone & rsiRecovery & upTrend, "signal"] = 1

  # 売り: 直近でBB上バンド割れ + RSI反落 + 下降トレンド
  df.loc[bbHighZone & rsiReversal & downTrend, "signal"] = -1

  # ウォームアップ期間(trend_maがNaN)はシグナルを出さない
  df.loc[df["trend_ma"].isna(), "signal"] = 0

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
# EMA + ドンチャン補完
# ---------------------------------------------------------------------------

def calcEmaDon(df: pd.DataFrame,
               short: int = 10,
               long: int = 50,
               entryPeriod: int = 20,
               exitPeriod: int = 10,
               volFilter: float = 1.2) -> pd.DataFrame:
  """
  EMAクロスをメインに、EMAがポジション不在時のみドンチャンで補完。
  売りはEMAのデッドクロスに従う。
  """
  dfE = calcEma(df, short=short, long=long)
  dfD = calcDonchian(df, entryPeriod=entryPeriod, exitPeriod=exitPeriod, volFilter=volFilter)

  # EMAのポジション状態を追跡（.valuesで高速化）
  sigVals = dfE["signal"].values
  posArr = np.zeros(len(sigVals), dtype=int)
  pos = 0
  for i in range(len(sigVals)):
    if sigVals[i] == 1:
      pos = 1
    elif sigVals[i] == -1:
      pos = 0
    posArr[i] = pos
  emaPos = pd.Series(posArr, index=df.index)

  # EMAシグナルをベースに、EMA不在時のドンチャン買いで補完
  result = dfE.copy()
  donBuy = dfD["signal"] == 1
  result.loc[donBuy & (emaPos == 0), "signal"] = 1

  return result


# ---------------------------------------------------------------------------
# VWAP 乖離
# ---------------------------------------------------------------------------

def calcVwap(df: pd.DataFrame,
             threshold: float = 1.0) -> pd.DataFrame:
  """
  VWAP乖離率で平均回帰を狙う。
  日付が変わるたびに累積をリセットして日次VWAPを計算する。
  volumeが無い場合はSMA代替(period=20)でフォールバック。
  """
  df = df.copy()

  if "volume" in df.columns and df["volume"].sum() > 0:
    # 日付ごとにグループ化して累積をリセット（日次VWAP）
    date = df.index.normalize() if hasattr(df.index, "normalize") else pd.to_datetime(df.index).normalize()
    tp = df["close"] * df["volume"]
    cumTp = tp.groupby(date).cumsum()
    cumVol = df["volume"].groupby(date).cumsum()
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
# ドンチャンチャネル ブレイクアウト
# ---------------------------------------------------------------------------

def calcDonchian(df: pd.DataFrame,
                 entryPeriod: int = 20,
                 exitPeriod: int = 10,
                 volFilter: float = 1.2) -> pd.DataFrame:
  """
  ドンチャンチャネル ブレイクアウト（Turtle Trading スタイル）

  買い: 終値が直近entryPeriod日の高値を上抜け（+ 出来高フィルター）
  売り: 終値が直近exitPeriod日の安値を下抜け
  volFilter: ブレイクアウト日の出来高が直近平均のN倍以上で確認（0=無効）
  """
  df = df.copy()

  # チャネル計算（前日までのデータで判定 → shift(1)）
  df["dc_upper"] = df["high"].rolling(entryPeriod).max().shift(1)
  df["dc_lower"] = df["low"].rolling(exitPeriod).min().shift(1)

  df["signal"] = 0

  # 買い: 終値がエントリーチャネル上限を上抜け
  breakout = df["close"] > df["dc_upper"]

  # 出来高フィルター（出来高データがあり、volFilter > 0 の場合のみ）
  if volFilter > 0 and "volume" in df.columns and df["volume"].sum() > 0:
    avgVol = df["volume"].rolling(entryPeriod).mean().shift(1)
    volOk = df["volume"] > avgVol * volFilter
    breakout = breakout & volOk

  df.loc[breakout, "signal"] = 1

  # 売り: 終値がエグジットチャネル下限を下抜け
  df.loc[df["close"] < df["dc_lower"], "signal"] = -1

  # ウォームアップ期間はシグナルを出さない
  df.loc[df["dc_upper"].isna(), "signal"] = 0

  return df


# ---------------------------------------------------------------------------
# 戦略レジストリ
# ---------------------------------------------------------------------------

STRATEGIES = {
  "rsi": {"fn": calcRsi, "name": "RSI逆張り", "defaults": {"period": 14, "oversold": 30, "overbought": 70}},
  "bb":  {"fn": calcBb,  "name": "ボリンジャーバンド", "defaults": {"period": 20, "std": 2.0}},
  "bb_trend": {"fn": calcBbTrend, "name": "BB+トレンドフィルター", "defaults": {"period": 20, "std": 2.0, "trendMaPeriod": 200, "rsiPeriod": 14, "rsiOversold": 40, "rsiOverbought": 60, "lookback": 5}},
  "ema": {"fn": calcEma, "name": "EMAクロス", "defaults": {"short": 5, "long": 20}},
  "vwap": {"fn": calcVwap, "name": "VWAP乖離", "defaults": {"threshold": 1.0}},
  "donchian": {"fn": calcDonchian, "name": "ドンチャンブレイクアウト", "defaults": {"entryPeriod": 20, "exitPeriod": 10, "volFilter": 1.2}},
  "ema_don": {"fn": calcEmaDon, "name": "EMA+ドンチャン補完", "defaults": {"short": 10, "long": 50, "entryPeriod": 20, "exitPeriod": 10, "volFilter": 1.2}},
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
