"""
バックテスト結果の可視化

累積リターンチャート等を Plotly HTML で出力。
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "leadlag"


def plotCumulativeReturns(portfolio, portfolioEnh=None, outputPath=None):
  """
  累積リターンチャートを生成。
  Enhanced版があれば比較表示。

  Args:
    portfolio: constructPortfolio() の出力 (ベース)
    portfolioEnh: Enhanced版のポートフォリオ (オプション)
    outputPath: HTML出力先
  """
  if outputPath is None:
    outputPath = DATA_DIR / "chart_cumulative.html"
  outputPath = Path(outputPath)
  outputPath.parent.mkdir(parents=True, exist_ok=True)

  cumRet = (1 + portfolio["port_return"]).cumprod()

  # ドローダウン (メイン戦略)
  mainCum = cumRet
  if portfolioEnh is not None:
    mainCum = (1 + portfolioEnh["port_return"]).cumprod()
  peak = mainCum.cummax()
  drawdown = (mainCum / peak - 1) * 100

  fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=[0.7, 0.3],
    subplot_titles=["累積リターン", "ドローダウン (%)"],
  )

  # ベース PCA SUB
  fig.add_trace(
    go.Scatter(x=cumRet.index, y=cumRet, name="PCA SUB",
               line=dict(color="#4488ff", width=1.5, dash="dot")),
    row=1, col=1,
  )

  # Enhanced (PCA + JP MOM)
  if portfolioEnh is not None:
    cumEnh = (1 + portfolioEnh["port_return"]).cumprod()
    fig.add_trace(
      go.Scatter(x=cumEnh.index, y=cumEnh, name="PCA + JP MOM",
                 line=dict(color="#00d4aa", width=2.5)),
      row=1, col=1,
    )

  # ドローダウン
  fig.add_trace(
    go.Scatter(x=drawdown.index, y=drawdown, name="Drawdown",
               fill="tozeroy", line=dict(color="#ff4444", width=1),
               fillcolor="rgba(255,68,68,0.3)"),
    row=2, col=1,
  )

  title = "日米リードラグ戦略 — 累積リターン比較"
  fig.update_layout(
    title=title,
    template="plotly_dark",
    height=700,
    showlegend=True,
    legend=dict(x=0.01, y=0.99),
  )
  fig.update_yaxes(title_text="累積リターン", row=1, col=1)
  fig.update_yaxes(title_text="DD (%)", row=2, col=1)

  fig.write_html(str(outputPath))
  print(f"チャート保存: {outputPath}")
