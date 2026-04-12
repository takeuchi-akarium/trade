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


def calcFundaScore(goldHistory: list[float], tnxHistory: list[float],
                    fngHistory: list[int], window: int = 90) -> float:
    """
    BTC トレンド予測ファンダスコアを算出

    3指標のZ-scoreを相関強度ウェイトで合算:
      - ゴールド50日モメンタム(反転): 相関-0.31 → weight 0.41
      - 10年債20日変化:              相関+0.28 → weight 0.37
      - FnG変化速度(7d-30d):         相関+0.17 → weight 0.22

    戻り値: おおよそ -2 ~ +2 の連続値。0=中立、+方向=BTC強気
    """
    import numpy as np

    def _zscore(values, w):
        if len(values) < w + 1:
            return 0.0
        arr = np.array(values, dtype=float)
        mean = np.mean(arr[-w:])
        std = np.std(arr[-w:])
        if std == 0:
            return 0.0
        return (arr[-1] - mean) / std

    # ゴールド50日モメンタム（反転）
    goldZ = 0.0
    if len(goldHistory) >= 51:
        mom50 = (goldHistory[-1] / goldHistory[-51] - 1) * 100
        # 直近windowのモメンタム系列からZ-score
        moms = []
        for i in range(50, len(goldHistory)):
            moms.append((goldHistory[i] / goldHistory[i - 50] - 1) * 100)
        if len(moms) >= 2:
            m = np.mean(moms[-min(window, len(moms)):])
            s = np.std(moms[-min(window, len(moms)):])
            goldZ = -(mom50 - m) / s if s > 0 else 0.0  # 反転

    # 10年債20日変化
    tnxZ = 0.0
    if len(tnxHistory) >= 21:
        chg20 = tnxHistory[-1] - tnxHistory[-21]
        chgs = []
        for i in range(20, len(tnxHistory)):
            chgs.append(tnxHistory[i] - tnxHistory[i - 20])
        if len(chgs) >= 2:
            m = np.mean(chgs[-min(window, len(chgs)):])
            s = np.std(chgs[-min(window, len(chgs)):])
            tnxZ = (chg20 - m) / s if s > 0 else 0.0

    # FnG変化速度 (7日平均 - 30日平均)
    fngZ = 0.0
    if len(fngHistory) >= 30:
        fng = np.array(fngHistory, dtype=float)
        sma7 = np.mean(fng[-7:])
        sma30 = np.mean(fng[-30:])
        revert = sma7 - sma30
        # 直近windowの系列からZ-score
        reverts = []
        for i in range(29, len(fng)):
            s7 = np.mean(fng[max(0, i - 6):i + 1])
            s30 = np.mean(fng[max(0, i - 29):i + 1])
            reverts.append(s7 - s30)
        if len(reverts) >= 2:
            m = np.mean(reverts[-min(window, len(reverts)):])
            s = np.std(reverts[-min(window, len(reverts)):])
            fngZ = (revert - m) / s if s > 0 else 0.0

    return 0.41 * goldZ + 0.37 * tnxZ + 0.22 * fngZ


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
