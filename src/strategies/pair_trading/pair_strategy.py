"""
ペアトレード戦略モジュール（x-trade.jp 方式）

US100（ナスダック）買い × US30（ダウ）売りのスプレッド戦略。
スプレッドの平均回帰をボリンジャーバンドで検出してシグナルを生成する。
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# スプレッド計算
# ---------------------------------------------------------------------------

def calcSpread(
  dfNasdaq: pd.DataFrame,
  dfDow: pd.DataFrame,
  nasdaqLots: float = 10,
  dowLots: float = 4,
) -> pd.DataFrame:
  """
  2銘柄の終値からロット加重スプレッドを算出。

  spread = nasdaqLots * nasdaq_return - dowLots * dow_return
  （価格水準が異なるため、リターンベースで比較）

  Returns:
    DataFrame with columns: nasdaq_close, dow_close, spread, nasdaq_ret, dow_ret
  """
  # 共通日付でアライン
  merged = pd.DataFrame({
    "nasdaq_close": dfNasdaq["close"],
    "dow_close": dfDow["close"],
  }).dropna()

  # 日次リターン（%）
  merged["nasdaq_ret"] = merged["nasdaq_close"].pct_change() * 100
  merged["dow_ret"] = merged["dow_close"].pct_change() * 100

  # ロット加重スプレッド: ナスダック買い - ダウ売り → 正ならペア利益
  merged["spread"] = nasdaqLots * merged["nasdaq_ret"] - dowLots * merged["dow_ret"]

  # 累積スプレッド（バックテスト用）
  merged["spread_cum"] = merged["spread"].cumsum()

  return merged.dropna()


# ---------------------------------------------------------------------------
# シグナル生成: ボリンジャーバンド方式
# ---------------------------------------------------------------------------

def calcPairSignalBb(
  df: pd.DataFrame,
  period: int = 20,
  entryStd: float = 2.0,
  exitStd: float = 0.0,
) -> pd.DataFrame:
  """
  累積スプレッドのボリンジャーバンドでシグナル生成。

  - 累積スプレッドが下バンド割れ → 買い（ペアエントリー）
  - 累積スプレッドが中央線（or exitStd）回帰 → 売り（ペアクローズ）
  - 累積スプレッドが上バンド超え → 売り（逆方向エントリーは行わず利確のみ）

  signal: +1=エントリー, -1=クローズ, 0=様子見
  """
  df = df.copy()
  sc = df["spread_cum"]

  df["bb_mid"] = sc.rolling(period).mean()
  rollStd = sc.rolling(period).std()
  df["bb_upper"] = df["bb_mid"] + entryStd * rollStd
  df["bb_lower"] = df["bb_mid"] - entryStd * rollStd
  df["bb_exit_upper"] = df["bb_mid"] + exitStd * rollStd
  df["bb_exit_lower"] = df["bb_mid"] - exitStd * rollStd

  df["signal"] = 0

  # 下バンド割れ → エントリー（スプレッドが異常に縮小 → 回復を狙う）
  df.loc[sc <= df["bb_lower"], "signal"] = 1

  # 中央回帰 or 上バンド超え → クローズ
  df.loc[sc >= df["bb_exit_upper"], "signal"] = -1

  return df


# ---------------------------------------------------------------------------
# シグナル生成: EMA乖離方式
# ---------------------------------------------------------------------------

def calcPairSignalEma(
  df: pd.DataFrame,
  short: int = 5,
  long: int = 20,
) -> pd.DataFrame:
  """
  累積スプレッドのEMAクロスでシグナル生成。

  - 短期EMA > 長期EMA へクロス → 買い
  - 短期EMA < 長期EMA へクロス → 売り
  """
  df = df.copy()
  sc = df["spread_cum"]

  df["ema_short"] = sc.ewm(span=short, adjust=False).mean()
  df["ema_long"] = sc.ewm(span=long, adjust=False).mean()

  diff = df["ema_short"] - df["ema_long"]
  prevDiff = diff.shift(1)

  df["signal"] = 0
  df.loc[(diff > 0) & (prevDiff <= 0), "signal"] = 1   # ゴールデンクロス
  df.loc[(diff < 0) & (prevDiff >= 0), "signal"] = -1  # デッドクロス

  return df


# ---------------------------------------------------------------------------
# 戦略レジストリ
# ---------------------------------------------------------------------------

PAIR_STRATEGIES = {
  "bb": {
    "fn": calcPairSignalBb,
    "name": "スプレッドBB",
    "defaults": {"period": 20, "entryStd": 2.0, "exitStd": 0.0},
  },
  "ema": {
    "fn": calcPairSignalEma,
    "name": "スプレッドEMA",
    "defaults": {"short": 5, "long": 20},
  },
}


def calcPairSignals(df: pd.DataFrame, strategyKey: str, **kwargs) -> pd.DataFrame:
  """指定戦略のペアシグナルを計算"""
  entry = PAIR_STRATEGIES[strategyKey]
  params = {**entry["defaults"], **kwargs}
  return entry["fn"](df, **params)
