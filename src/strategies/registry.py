"""
戦略レジストリ

各戦略の __init__.py で register() を呼ぶことで自動登録される。
simulator から list / get で戦略を取得する。
"""

from strategies.base import Strategy

STRATEGIES: dict[str, Strategy] = {}


def register(strategyInstance: Strategy) -> None:
  """戦略インスタンスを登録"""
  STRATEGIES[strategyInstance.name] = strategyInstance


def listStrategies() -> list[Strategy]:
  """登録済み全戦略を返す"""
  return list(STRATEGIES.values())


def getStrategy(name: str) -> Strategy:
  """名前で戦略を取得。見つからなければ KeyError"""
  if name not in STRATEGIES:
    available = ", ".join(STRATEGIES.keys())
    raise KeyError(f"戦略 '{name}' が見つかりません。利用可能: {available}")
  return STRATEGIES[name]
