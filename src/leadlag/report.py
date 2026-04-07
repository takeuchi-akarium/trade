"""
レポート生成 + AIコメント

毎朝のDiscord通知用レポートを組み立てる。
Claude APIでファクター分析に基づくAIコメントを生成。
"""

import os
from datetime import datetime, timedelta, timezone

from leadlag.constants import US_SECTOR_NAMES, JP_SECTOR_NAMES


def buildReport(positions, todaySignal, runningMetrics, aiComment=None):
  """
  Discord通知用のレポート文字列を組み立てる。

  Args:
    positions: selectPositions() の出力 {"long": [...], "short": [...]}
    todaySignal: generateTodaySignal() の出力
    runningMetrics: calcRunningMetrics() の出力
    aiComment: AIコメント文字列 (Noneならスキップ)

  Returns:
    str: レポート文字列
  """
  # 実行日 (JST) をヘッダーに表示
  jst = timezone(timedelta(hours=9))
  now = datetime.now(jst)
  weekdays = ["月", "火", "水", "木", "金", "土", "日"]
  execDateStr = f"{now.strftime('%Y-%m-%d')}({weekdays[now.weekday()]})"

  # データ基準日（最終取引日）
  date = todaySignal["date"]
  if hasattr(date, "strftime"):
    dataDateStr = f"{date.strftime('%Y-%m-%d')}({weekdays[date.weekday()]})"
  else:
    dataDateStr = str(date)

  lines = []
  lines.append(f"=== 日米リードラグ シグナル {execDateStr} ===")
  if execDateStr != dataDateStr:
    lines.append(f"  （データ基準日: {dataDateStr}）")
  lines.append("")

  # 確信度
  confidence = todaySignal.get("confidence", None)
  if confidence is not None:
    if confidence >= 1.3:
      level = "高"
      advice = "通常通りエントリー"
    elif confidence >= 0.9:
      level = "中"
      advice = "ポジション控えめ推奨"
    else:
      level = "低"
      advice = "様子見推奨"
    lines.append(f"■ 確信度: {level} ({confidence:.2f}) — {advice}")
    lines.append("")

  # ロングポジション
  lines.append("■ 本日の推奨ポジション")
  lines.append("【ロング（寄付き買い→引け売り）】")
  for p in positions["long"]:
    score = f"+{p['score']:.4f}" if p['score'] >= 0 else f"{p['score']:.4f}"
    lines.append(f"  {p['ticker']} {p['name']:<10s} {score}")

  lines.append("")
  lines.append("【ショート（様子見）】")
  for p in positions["short"]:
    score = f"+{p['score']:.4f}" if p['score'] >= 0 else f"{p['score']:.4f}"
    lines.append(f"  {p['ticker']} {p['name']:<10s} {score}")

  # 米国市場サマリ
  lines.append("")
  lines.append("■ 米国市場（前日）")
  usRet = todaySignal["usReturns"]
  # 変動幅上位5セクターを表示
  sortedUs = sorted(usRet.items(), key=lambda x: abs(x[1]), reverse=True)
  usParts = []
  for ticker, ret in sortedUs[:5]:
    name = US_SECTOR_NAMES.get(ticker, ticker)
    sign = "+" if ret >= 0 else ""
    usParts.append(f"{name} {sign}{ret * 100:.1f}%")
  lines.append("  " + " / ".join(usParts))

  # ファクタースコア
  fs = todaySignal["factorScores"]
  factorNames = ["グローバル", "国スプレッド", "シクリカル"]
  fsParts = [f"{factorNames[i]}: {fs[i]:+.3f}" for i in range(min(len(fs), len(factorNames)))]
  lines.append(f"  ファクター: {' / '.join(fsParts)}")

  # AIコメント
  if aiComment:
    lines.append("")
    lines.append("■ AIコメント")
    lines.append(aiComment)

  # 実績
  lines.append("")
  lines.append("■ 実績")
  lines.append(
    f"  前日: {runningMetrics['lastDay']:+.2f}%"
    f" / 月次: {runningMetrics['mtd']:+.2f}%"
    f" / 年初来: {runningMetrics['ytd']:+.2f}%"
  )

  lines.append("=" * 40)
  return "\n".join(lines)


def generateAiComment(todaySignal, positions):
  """
  Claude APIでAIコメントを生成する。

  市場データ・シグナル・ファクタースコアを渡し、
  簡潔な日本語の市場解説を生成。
  """
  apiKey = os.environ.get("ANTHROPIC_API_KEY", "")
  if not apiKey:
    return None

  try:
    import anthropic
    client = anthropic.Anthropic(api_key=apiKey)
  except Exception:
    return None

  # 米国リターン情報
  usLines = []
  for ticker, ret in sorted(todaySignal["usReturns"].items(), key=lambda x: x[1], reverse=True):
    name = US_SECTOR_NAMES.get(ticker, ticker)
    usLines.append(f"  {name}: {ret * 100:+.2f}%")

  # シグナル情報
  longNames = [f"{p['name']}({p['score']:+.4f})" for p in positions["long"]]
  shortNames = [f"{p['name']}({p['score']:+.4f})" for p in positions["short"]]

  fs = todaySignal["factorScores"]
  factorNames = ["グローバル", "国スプレッド", "シクリカル/ディフェンシブ"]

  prompt = f"""以下の市場データに基づき、本日の日本株セクターETFの見通しを3-4文で簡潔にコメントしてください。

【米国セクターリターン（前日）】
{chr(10).join(usLines)}

【共通ファクタースコア】
{chr(10).join(f"  {factorNames[i]}: {fs[i]:+.3f}" for i in range(min(len(fs), len(factorNames))))}

【本日のロング推奨】 {', '.join(longNames)}
【本日のショート推奨】 {', '.join(shortNames)}

注意:
- 日米の取引時間帯の違い（米国→日本への情報波及）に基づく分析です
- ファクタースコアの正負と大きさに着目し、どのようなテーマが波及しそうか述べてください
- 専門用語は避け、投資判断の参考になる表現にしてください
- 3-4文以内で簡潔に"""

  try:
    message = client.messages.create(
      model="claude-haiku-4-5-20251001",
      max_tokens=300,
      messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()
  except Exception as e:
    return f"(AIコメント生成失敗: {e})"
