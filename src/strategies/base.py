"""
戦略の共通インターフェース

全戦略はこの Strategy クラスを継承して実装する。
シミュレーター (simulator/) がこのインターフェースを通じて
データ取得 → シグナル生成 → バックテスト → 結果出力 を統一的に実行する。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class BacktestResult:
  """全戦略が返す統一フォーマット"""
  strategyName: str
  symbol: str
  interval: str
  trades: list[dict] = field(default_factory=list)
  equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
  metrics: dict = field(default_factory=dict)
  params: dict = field(default_factory=dict)
  metadata: dict = field(default_factory=dict)


class Strategy(ABC):
  """全戦略が実装する共通インターフェース"""

  name: str = ""
  description: str = ""
  category: str = ""  # "short_term", "long_term", "pair", "macro"
  version: str = "1.0.0"
  defaultParams: dict = {}

  @abstractmethod
  def fetchData(self, symbol: str, interval: str = "1d", **kwargs) -> pd.DataFrame:
    """データ取得。各戦略が独自のデータソースから取得する"""
    ...

  @abstractmethod
  def generateSignals(self, data: pd.DataFrame, **params) -> pd.DataFrame:
    """
    シグナル生成。dataに "signal" 列を追加して返す。
    signal: +1=買い, -1=売り, 0=様子見
    """
    ...

  @abstractmethod
  def backtest(self, data: pd.DataFrame, **params) -> BacktestResult:
    """バックテスト実行。共通の BacktestResult を返す"""
    ...

  def getParams(self, **overrides) -> dict:
    """デフォルトパラメータにオーバーライドを適用（None値はデフォルトを保持）"""
    filtered = {k: v for k, v in overrides.items() if v is not None}
    return {**self.defaultParams, **filtered}
