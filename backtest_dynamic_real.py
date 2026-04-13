# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import numpy as np
import pandas as pd
import strategies
from strategies.registry import getStrategy
from strategies.scalping.backtest import runBacktest, runBacktestLongShort

# 実データ取得
bbStrategy   = getStrategy('bb')
bbLsStrategy = getStrategy('bb_ls')

data = bbStrategy.fetchData(symbol='BTCUSDT', interval='1d', years=3)
print(f'データ期間: {data.index[0].date()} ~ {data.index[-1].date()} ({len(data)}行)')

# シグナル生成
dfBb   = bbStrategy.generateSignals(data.copy())
dfBbLs = bbLsStrategy.generateSignals(data.copy())

# トレンド判定用 200日MA
trendMa = data['close'].rolling(200).mean()

initialCapital = 100_000
feePct = 0.1

_, eqBb   = runBacktest(dfBb,   initialCapital, feePct / 100)
_, eqBbLs = runBacktestLongShort(dfBbLs, initialCapital, feePct / 100, stopLossPct=5.0)

retBb   = eqBb.pct_change().fillna(0)
retBbLs = eqBbLs.pct_change().fillna(0)

REGIME_WEIGHTS = {
    'uptrend':   (0.60, 0.20, 0.20),
    'range':     (0.30, 0.50, 0.20),
    'downtrend': (0.10, 0.20, 0.70),
}

# 比率変動制シミュレーション
equity = initialCapital
equityList    = []
regimeHistory = []

for i in range(len(data)):
    close = data['close'].iloc[i]
    ma    = trendMa.iloc[i]

    if np.isnan(ma):
        regime = 'range'
    elif close > ma * 1.02:
        regime = 'uptrend'
    elif close < ma * 0.98:
        regime = 'downtrend'
    else:
        regime = 'range'

    wBb, wBbLs, wCash = REGIME_WEIGHTS[regime]
    rBb   = retBb.iloc[i]   if i < len(retBb)   else 0.0
    rBbLs = retBbLs.iloc[i] if i < len(retBbLs) else 0.0
    portfolioReturn = wBb * rBb + wBbLs * rBbLs  # cash返率=0
    equity *= (1 + portfolioReturn)
    equityList.append(equity)
    regimeHistory.append(regime)

eqSeries    = pd.Series(equityList, index=data.index)
finalValue  = equityList[-1]
totalReturn = (finalValue - initialCapital) / initialCapital * 100
peak        = eqSeries.expanding().max()
mdd         = ((eqSeries - peak) / peak * 100).min()

years    = len(data) / 365
annDyn   = ((finalValue / initialCapital) ** (1 / years) - 1) * 100
dailyRet = eqSeries.pct_change().dropna()
sharpe   = (dailyRet.mean() / dailyRet.std()) * (252 ** 0.5) if dailyRet.std() > 0 else 0.0

regimeCounts = {}
for r in regimeHistory:
    regimeCounts[r] = regimeCounts.get(r, 0) + 1

# bb単体
bbFinal  = eqBb.iloc[-1]
bbReturn = (bbFinal - initialCapital) / initialCapital * 100
bbPeak   = eqBb.expanding().max()
bbMdd    = ((eqBb - bbPeak) / bbPeak * 100).min()
bbAnn    = ((bbFinal / initialCapital) ** (1 / years) - 1) * 100
bbDly    = eqBb.pct_change().dropna()
bbSharpe = (bbDly.mean() / bbDly.std()) * (252**0.5) if bbDly.std() > 0 else 0.0

# bb_ls単体
bbLsFinal  = eqBbLs.iloc[-1]
bbLsReturn = (bbLsFinal - initialCapital) / initialCapital * 100
bbLsPeak   = eqBbLs.expanding().max()
bbLsMdd    = ((eqBbLs - bbLsPeak) / bbLsPeak * 100).min()
bbLsAnn    = ((bbLsFinal / initialCapital) ** (1 / years) - 1) * 100
bbLsDly    = eqBbLs.pct_change().dropna()
bbLsSharpe = (bbLsDly.mean() / bbLsDly.std()) * (252**0.5) if bbLsDly.std() > 0 else 0.0

# 固定配分 (bb50+ls30+cash20)
fixedEquity = initialCapital
fixedList   = []
for i in range(len(data)):
    rBb_i   = retBb.iloc[i]   if i < len(retBb)   else 0.0
    rBbLs_i = retBbLs.iloc[i] if i < len(retBbLs) else 0.0
    fixedReturn = 0.50 * rBb_i + 0.30 * rBbLs_i
    fixedEquity *= (1 + fixedReturn)
    fixedList.append(fixedEquity)

fixedSeries     = pd.Series(fixedList, index=data.index)
fixedFinal      = fixedList[-1]
fixedTotalRet   = (fixedFinal - initialCapital) / initialCapital * 100
fixedPeak       = fixedSeries.expanding().max()
fixedMdd        = ((fixedSeries - fixedPeak) / fixedPeak * 100).min()
fixedAnn        = ((fixedFinal / initialCapital) ** (1 / years) - 1) * 100
fixedDly        = fixedSeries.pct_change().dropna()
fixedSharpe     = (fixedDly.mean() / fixedDly.std()) * (252**0.5) if fixedDly.std() > 0 else 0.0

# 出力
SEP = '=' * 72

print()
print(SEP)
print('  実データバックテスト: BTCUSDT 日足')
print(SEP)
print(f'  期間    : {data.index[0].date()} ~ {data.index[-1].date()}')
print(f'  データ  : {len(data)} 本  ({years:.1f} 年間)')
print(f'  初期資産: {initialCapital:,.0f} USDT')
print(f'  手数料  : {feePct}% / 片道   |   bb_ls ストップロス: 5%')
print()
print(f'  レジーム分布:')
print(f'    uptrend  (強気) : {regimeCounts.get("uptrend", 0):4d} 日  bb60% / bb_ls20% / cash20%')
print(f'    range    (中立) : {regimeCounts.get("range", 0):4d} 日  bb30% / bb_ls50% / cash20%')
print(f'    downtrend(弱気) : {regimeCounts.get("downtrend", 0):4d} 日  bb10% / bb_ls20% / cash70%')
print()
print(f'  {"配分方式":<22s} {"総リターン":>10s} {"年率リターン":>12s} {"最終資産":>12s} {"MDD":>10s} {"Sharpe":>8s}')
print(f'  {"-" * 74}')
print(f'  {"比率変動制":<22s} {totalReturn:>+9.2f}% {annDyn:>+11.2f}% {finalValue:>12,.0f} {mdd:>+9.2f}% {sharpe:>7.2f}')
print(f'  {"固定(bb50+ls30+cash20)":<22s} {fixedTotalRet:>+9.2f}% {fixedAnn:>+11.2f}% {fixedFinal:>12,.0f} {fixedMdd:>+9.2f}% {fixedSharpe:>7.2f}')
print(f'  {"bb単体(ロングのみ)":<22s} {bbReturn:>+9.2f}% {bbAnn:>+11.2f}% {bbFinal:>12,.0f} {bbMdd:>+9.2f}% {bbSharpe:>7.2f}')
print(f'  {"bb_ls単体(L/S)":<22s} {bbLsReturn:>+9.2f}% {bbLsAnn:>+11.2f}% {bbLsFinal:>12,.0f} {bbLsMdd:>+9.2f}% {bbLsSharpe:>7.2f}')
print()
