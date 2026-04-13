"""
デュアルモメンタム レポート生成 (朝バッチ用)
"""

from dual_momentum.constants import TICKER_NAMES


def buildReport(todaySignal, prevSignal=None):
  """
  朝バッチ用のレポート文字列を生成。

  Args:
    todaySignal: generateTodaySignal() の戻り値
    prevSignal: 前月のシグナル (変化検出用)

  Returns:
    str: レポート文字列
  """
  if todaySignal is None:
    return "  データ不足"

  sig = todaySignal["signal"]
  sigName = todaySignal["signal_name"]
  chosenEq = todaySignal["chosen_equity"]
  chosenEqName = todaySignal["chosen_equity_name"]
  momUs = todaySignal["momentum_us"]
  momIntl = todaySignal["momentum_intl"]
  momTbill = todaySignal["momentum_tbill"]

  # シグナルアイコン
  if sig == "SPY":
    icon = "米国株"
  elif sig == "EFA":
    icon = "先進国株"
  else:
    icon = "債券退避"

  lines = [f"  判定: {icon} → {sigName} ({sig})"]
  lines.append(f"  12ヶ月モメンタム: SPY {momUs:+.1f}% / EFA {momIntl:+.1f}% / BIL {momTbill:+.1f}%")
  lines.append(f"  相対モメンタム勝者: {chosenEqName}")

  # シグナル変化の検出
  if prevSignal and prevSignal != sig:
    prevName = TICKER_NAMES.get(prevSignal, prevSignal)
    lines.append(f"  ** リバランス: {prevName} → {sigName} **")

  return "\n".join(lines)
