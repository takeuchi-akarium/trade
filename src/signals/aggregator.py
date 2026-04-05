"""
シグナル集約モジュール

各コレクターからデータを収集 → スコア化 → BUY/HOLD/SELL シグナルを返す
"""

from signals.collectors.macro_collector import get_fear_greed, get_vix
from signals.scorer import score_fear_greed, score_vix, aggregate


def collect_and_score(weights: dict | None = None) -> dict:
    """
    全コレクターを実行してスコアと詳細を返す

    戻り値例:
    {
        "total": 22,
        "scores": {"fear_greed": 44, "vix": 0},
        "details": {"fear_greed": "72 (Greed)", "vix": "21.3"},
    }
    """
    scores = {}
    details = {}

    # Fear & Greed
    try:
        fg = get_fear_greed()
        scores["fear_greed"] = score_fear_greed(fg)
        details["fear_greed"] = f"{fg['value']} ({fg['label']})"
    except Exception as e:
        details["fear_greed"] = f"取得失敗: {e}"

    # VIX
    try:
        vix = get_vix()
        scores["vix"] = score_vix(vix)
        details["vix"] = f"{vix:.1f}" if vix is not None else "N/A"
    except Exception as e:
        details["vix"] = f"取得失敗: {e}"

    total = aggregate(scores, weights)
    return {"total": total, "scores": scores, "details": details}


def to_signal(total: int, buy_threshold: int = 30, sell_threshold: int = -30) -> str:
    """スコア → BUY / HOLD / SELL"""
    if total >= buy_threshold:
        return "BUY"
    elif total <= sell_threshold:
        return "SELL"
    return "HOLD"
