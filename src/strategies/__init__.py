"""
戦略パッケージ

import strategies するだけで全戦略が自動登録される。
"""

# 各戦略パッケージを import → register() が呼ばれて自動登録
import strategies.scalping
import strategies.btc
import strategies.dual_momentum
import strategies.leadlag
import strategies.pair_trading
import strategies.grid
import strategies.adaptive
import strategies.jp_stock

from strategies.registry import listStrategies, getStrategy
