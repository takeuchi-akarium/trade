"""
各指標の生データ → -100〜+100 のスコアに変換

スコアの意味:
  +100 : 強い買いシグナル
     0 : 中立
  -100 : 強い売りシグナル
"""


def score_fear_greed(data: dict) -> int:
    """
    Fear & Greed 0〜100 → -100〜+100
    50 = 中立、100 = 極度の強欲（強気）、0 = 極度の恐怖（弱気）
    """
    return (data["value"] - 50) * 2


def score_vix(vix: float | None) -> int:
    """
    VIX が高い = 市場の恐怖 = 弱気シグナル
    閾値は過去の経験則ベース（カスタマイズ可）
    """
    if vix is None:
        return 0
    if vix < 15:
        return 40    # 極めて低ボラ → 強気
    elif vix < 20:
        return 20
    elif vix < 25:
        return 0     # 中立
    elif vix < 30:
        return -30
    elif vix < 40:
        return -60
    else:
        return -100  # パニック水準


def aggregate(scores: dict, weights: dict | None = None) -> int:
    """
    スコアを重み付き平均で統合
    scores  : {"fear_greed": 44, "vix": -30, ...}
    weights : {"fear_greed": 1.0, "vix": 1.0, ...}  省略時は均等重み
    """
    if not scores:
        return 0
    if weights is None:
        weights = {k: 1.0 for k in scores}

    total_w = sum(weights.get(k, 1.0) for k in scores)
    if total_w == 0:
        return 0

    weighted = sum(v * weights.get(k, 1.0) for k, v in scores.items())
    return int(weighted / total_w)
