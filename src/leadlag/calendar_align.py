"""
日米営業日のアラインメント

米国市場クローズ (16:00 ET = 翌06:00 JST) 後に
日本市場が開く (09:00 JST) ため、
JP営業日 t の予測には直前のUS営業日のリターンを使う。
"""

import pandas as pd


def alignReturns(usRetCc, jpRetCc, jpRetOc):
  """
  日米リターンをアラインメントする。

  各JP営業日 d に対して、d より前の最も直近のUS営業日を紐付け。
  (月曜の日本 → 金曜の米国、祝日も自動処理)

  Args:
    usRetCc: 米国CC リターン (index=date, columns=US tickers)
    jpRetCc: 日本CC リターン (index=date, columns=JP tickers)
    jpRetOc: 日本OC リターン (index=date, columns=JP tickers)

  Returns:
    DataFrame: JP営業日でインデックス。
      us_cc_{ticker}: 紐付けられたUS当日CCリターン
      jp_cc_{ticker}: JP当日CCリターン (PCA用)
      jp_oc_{ticker}: JP当日OCリターン (戦略評価用)
  """
  usIndex = usRetCc.index.sort_values()
  rows = []

  for jpDate in jpRetCc.index:
    # jpDateより前の最も直近のUS営業日を探す
    candidates = usIndex[usIndex < jpDate]
    if len(candidates) == 0:
      continue

    usDate = candidates[-1]
    row = {"jp_date": jpDate, "us_date": usDate}

    # 米国CCリターン
    for col in usRetCc.columns:
      row[f"us_cc_{col}"] = usRetCc.loc[usDate, col]

    # 日本CCリターン
    for col in jpRetCc.columns:
      row[f"jp_cc_{col}"] = jpRetCc.loc[jpDate, col]

    # 日本OCリターン (戦略評価用)
    if jpDate in jpRetOc.index:
      for col in jpRetOc.columns:
        row[f"jp_oc_{col}"] = jpRetOc.loc[jpDate, col]

    rows.append(row)

  aligned = pd.DataFrame(rows)
  aligned.set_index("jp_date", inplace=True)
  aligned.index.name = "Date"
  return aligned
