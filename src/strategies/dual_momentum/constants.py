"""
デュアルモメンタム (GEM) 戦略の定数

Gary Antonacci の Global Equity Momentum に基づく。
相対モメンタム (米国株 vs 非米国先進国株) + 絶対モメンタム (vs Tビル) で
毎月アセットを切り替える。
"""

# --- 使用ETF ---
EQUITY_US = "SPY"       # S&P 500
EQUITY_INTL = "EFA"     # MSCI EAFE (非米国先進国)
BOND = "AGG"            # 米国総合債券 (退避先)
TBILL = "BIL"           # 短期国債 (絶対モメンタムの基準)

ALL_TICKERS = [EQUITY_US, EQUITY_INTL, BOND, TBILL]

TICKER_NAMES = {
  "SPY": "S&P 500",
  "EFA": "MSCI EAFE",
  "AGG": "米国総合債券",
  "BIL": "短期国債",
}

# --- パラメータ ---
LOOKBACK_MONTHS = 12    # モメンタムのルックバック期間
BACKTEST_START = "2005-01-01"
