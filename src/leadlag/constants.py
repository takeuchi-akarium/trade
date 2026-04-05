"""
日米業種リードラグ戦略の定数・パラメータ定義

論文: 部分空間正則化付きPCAを用いた日米業種リードラグ投資戦略
(中川ら, SIG-FIN-036, 2026)
"""

import numpy as np

# --- 米国セクターETF (Select Sector SPDR, 11銘柄) ---
US_TICKERS = [
  "XLB",   # Materials
  "XLC",   # Communication Services
  "XLE",   # Energy
  "XLF",   # Financials
  "XLI",   # Industrials
  "XLK",   # Technology
  "XLP",   # Consumer Staples
  "XLRE",  # Real Estate
  "XLU",   # Utilities
  "XLV",   # Health Care
  "XLY",   # Consumer Discretionary
]

US_SECTOR_NAMES = {
  "XLB": "Materials",
  "XLC": "Communication",
  "XLE": "Energy",
  "XLF": "Financials",
  "XLI": "Industrials",
  "XLK": "Technology",
  "XLP": "Consumer Staples",
  "XLRE": "Real Estate",
  "XLU": "Utilities",
  "XLV": "Health Care",
  "XLY": "Consumer Discr.",
}

# --- 日本 TOPIX-17 業種別ETF (NEXT FUNDS, 17銘柄) ---
JP_TICKERS = [
  "1617.T",  # 食品
  "1618.T",  # エネルギー資源
  "1619.T",  # 建設・資材
  "1620.T",  # 素材・化学
  "1621.T",  # 医薬品
  "1622.T",  # 自動車・輸送機
  "1623.T",  # 鉄鋼・非鉄
  "1624.T",  # 機械
  "1625.T",  # 電気・精密
  "1626.T",  # 情報通信・サービスその他
  "1627.T",  # 電力・ガス
  "1628.T",  # 運輸・物流
  "1629.T",  # 商社・卸売
  "1630.T",  # 小売
  "1631.T",  # 銀行
  "1632.T",  # 金融(除く銀行)
  "1633.T",  # 不動産
]

JP_SECTOR_NAMES = {
  "1617.T": "食品",
  "1618.T": "エネルギー資源",
  "1619.T": "建設・資材",
  "1620.T": "素材・化学",
  "1621.T": "医薬品",
  "1622.T": "自動車・輸送機",
  "1623.T": "鉄鋼・非鉄",
  "1624.T": "機械",
  "1625.T": "電気・精密",
  "1626.T": "情報通信・サービス",
  "1627.T": "電力・ガス",
  "1628.T": "運輸・物流",
  "1629.T": "商社・卸売",
  "1630.T": "小売",
  "1631.T": "銀行",
  "1632.T": "金融(除く銀行)",
  "1633.T": "不動産",
}

N_US = len(US_TICKERS)
N_JP = len(JP_TICKERS)
N_TOTAL = N_US + N_JP

# --- シクリカル / ディフェンシブ分類 (論文 Section 4.1) ---
CYCLICAL_US = ["XLB", "XLE", "XLF", "XLRE"]
DEFENSIVE_US = ["XLK", "XLP", "XLU", "XLV"]

CYCLICAL_JP = ["1618.T", "1625.T", "1629.T", "1631.T"]
DEFENSIVE_JP = ["1617.T", "1621.T", "1627.T", "1630.T"]

# --- デフォルトハイパーパラメータ ---
ROLLING_WINDOW = 60       # L=60営業日
LAMBDA_REG = 0.9          # 正則化重み (事前情報への寄り)
NUM_FACTORS = 3           # K=3 (共通ファクター数)
QUANTILE_CUTOFF = 0.3     # q=0.3 (ロング/ショートの閾値)

# C_full 推定期間
C_FULL_START = "2010-01-01"
C_FULL_END = "2014-12-31"


def buildPriorSubspace():
  """
  事前部分空間 V0 (N_TOTAL x 3) を構築する。

  3つの経済的に意味のある直交ベクトル:
    v1: グローバルファクター (全銘柄等ウェイト方向)
    v2: 国スプレッドファクター (US正, JP負)
    v3: シクリカル/ディフェンシブファクター
  """
  allTickers = US_TICKERS + JP_TICKERS

  # v1: グローバル (全て +1, 正規化)
  v1 = np.ones(N_TOTAL)
  v1 = v1 / np.linalg.norm(v1)

  # v2: 国スプレッド (US=+1, JP=-1, v1に直交化)
  v2 = np.array([1.0] * N_US + [-1.0] * N_JP)
  v2 = v2 - np.dot(v2, v1) * v1
  v2 = v2 / np.linalg.norm(v2)

  # v3: シクリカル/ディフェンシブ (該当=+1/-1, 中立=0, v1,v2に直交化)
  v3 = np.zeros(N_TOTAL)
  for i, t in enumerate(allTickers):
    if t in CYCLICAL_US or t in CYCLICAL_JP:
      v3[i] = 1.0
    elif t in DEFENSIVE_US or t in DEFENSIVE_JP:
      v3[i] = -1.0
  v3 = v3 - np.dot(v3, v1) * v1 - np.dot(v3, v2) * v2
  v3 = v3 / np.linalg.norm(v3)

  return np.column_stack([v1, v2, v3])
