"""
個別銘柄・ニュースのアラート送信

マクロシグナル（batch_15m.py）とは分離。
新着開示・ニュースを検知するたびに通知する（変化検知ではなく新着検知）。
"""

import json
from pathlib import Path
from common.notifier import notify

LATEST_SIGNAL_PATH = Path(__file__).parent.parent.parent / "data/signals/latest_signal.json"


def _get_macro_signal() -> str:
  """最新マクロシグナルを返す。ファイルがなければ HOLD"""
  try:
    if LATEST_SIGNAL_PATH.exists():
      return json.loads(LATEST_SIGNAL_PATH.read_text(encoding="utf-8")).get("signal", "HOLD")
  except Exception:
    pass
  return "HOLD"


def _build_hint(matched_kws: list[str], score: int, macro_signal: str) -> str:
  """キーワードとマクロ環境から株価示唆コメントを生成する"""
  # キーワード別の株価影響コメント
  KEYWORD_HINTS: dict[str, str] = {
    "上方修正":       "業績上振れで短期株価上昇が期待される",
    "業績予想の増額": "業績上振れで短期株価上昇が期待される",
    "増配":           "株主還元強化。配当利回り目的の買いが入りやすい",
    "特別配当":       "予想外の還元策。サプライズ買いが入りやすい",
    "自己株式取得":   "需給改善・EPS向上。株価下支え効果が見込まれる",
    "自社株買い":     "需給改善・EPS向上。株価下支え効果が見込まれる",
    "黒字転換":       "赤字脱却で評価改善。見直し買いが入りやすい",
    "過去最高":       "業績ピーク更新。強気材料として市場に評価されやすい",
    "増益":           "利益成長の継続確認。安心感から買いが入りやすい",
    "下方修正":       "業績悪化懸念。決算後の売り圧力に注意",
    "業績予想の減額": "業績悪化懸念。決算後の売り圧力に注意",
    "減配":           "株主還元後退。配当目的の投資家が売りに転じる可能性",
    "無配":           "配当消滅。高配当目的の投資家から売られやすい",
    "赤字転落":       "業績悪化が顕在化。格下げ・機関投資家の売りリスクあり",
    "赤字":           "収益悪化を示す。業績回復の見通しが鍵",
    "特別損失":       "一時的な損失計上。規模次第で株価への影響が変わる",
    "不祥事":         "信用リスクが急上昇。機関投資家の売りが集中しやすい",
    "訂正報告書":     "開示の信頼性に疑問符。売り優先で様子見が無難",
    "減益":           "利益成長の鈍化。期待値調整の売りが入りやすい",
    # ニュース
    "利下げ":         "金融緩和期待で株式市場全体に買いが入りやすい",
    "金融緩和":       "資金流入が促進され株価上昇の追い風になる",
    "景気回復":       "企業業績の改善期待から幅広く買いが入りやすい",
    "好決算":         "業績上振れ確認。関連銘柄に買いが集まりやすい",
    "急騰":           "短期的な過熱感に注意。高値掴みリスクあり",
    "最高値":         "上昇トレンド継続を示す。ただし利確売りも出やすい",
    "利上げ":         "資金調達コスト上昇で株式の割高感が増す。売り圧力に注意",
    "金利引き上げ":   "資金調達コスト上昇で株式の割高感が増す。売り圧力に注意",
    "景気後退":       "企業業績の悪化懸念が広がり、市場全体に売りが出やすい",
    "リセッション":   "企業業績の悪化懸念が広がり、市場全体に売りが出やすい",
    "貿易摩擦":       "輸出関連企業の業績悪化懸念。輸出株に売り圧力",
    "関税":           "コスト増・輸出減の懸念。影響業種の株価に注意",
    "破綻":           "信用不安が連鎖するリスク。金融株・関連株に波及しやすい",
    "倒産":           "債権者・取引先への影響波及に注意",
    "暴落":           "市場心理の急悪化。追証・投げ売りの連鎖に注意",
    "急落":           "短期的な売りが加速。下値支持線を確認してから判断",
    # 英語キーワード
    "rate cut":       "利下げ期待で株式市場に買いが入りやすい",
    "rate hike":      "利上げで株式の割高感が増す。売り圧力に注意",
    "rally":          "上昇の勢いが継続中。ただし過熱感に注意",
    "surge":          "急上昇。短期的な利確売りの可能性も",
    "record high":    "市場の強気継続を示す。ただし高値警戒も",
    "all-time high":  "市場の強気継続を示す。ただし高値警戒も",
    "recession":      "景気後退懸念。企業業績悪化で市場全体に売り圧力",
    "tariff":         "関税によるコスト増・貿易減の懸念",
    "trade war":      "貿易摩擦で輸出企業の業績悪化懸念",
    "bankruptcy":     "破綻で信用不安の連鎖リスク",
    "crash":          "市場急落。パニック売りの連鎖に注意",
    "plunge":         "急落。追証・投げ売りの連鎖に注意",
    "selloff":        "まとまった売りが発生。下値模索の展開",
    "sell-off":       "まとまった売りが発生。下値模索の展開",
    "earnings beat":  "市場予想を上回る決算。買い材料として評価されやすい",
    "stimulus":       "景気刺激策で市場に資金流入が期待される",
    "easing":         "金融緩和で株式市場に追い風",
    "recovery":       "景気回復期待で幅広い銘柄に買いが入りやすい",
    "bull market":    "強気相場継続。上昇トレンドの勢いが強い",
    "bear market":    "弱気相場入り。下落リスクへの備えが必要",
    "downturn":       "景気減速。企業業績の下振れに注意",
    "default":        "債務不履行で信用不安が広がるリスク",
    "inflation surge": "インフレ加速で利上げ観測が強まり株式に逆風",
  }

  hints = [KEYWORD_HINTS[kw] for kw in matched_kws if kw in KEYWORD_HINTS]
  hint_text = hints[0] if hints else ""

  # マクロ環境との組み合わせコメント
  if score > 0 and macro_signal == "BUY":
    macro_comment = "マクロ環境も強気で追い風"
  elif score > 0 and macro_signal == "SELL":
    macro_comment = "ただしマクロ環境は弱気(SELL)、注意が必要"
  elif score > 0:
    macro_comment = "マクロ環境は中立(HOLD)"
  elif score < 0 and macro_signal == "SELL":
    macro_comment = "マクロ環境も弱気で売り圧力が強まりやすい"
  elif score < 0 and macro_signal == "BUY":
    macro_comment = "ただしマクロ環境は強気(BUY)、個別要因の影響を見極めたい"
  else:
    macro_comment = "マクロ環境は中立(HOLD)"

  if hint_text:
    return f"{hint_text}。{macro_comment}"
  return macro_comment

# ---- TDnet キーワード ----

TDNET_BUY_KEYWORDS: dict[str, int] = {
    "上方修正": 80,
    "業績予想の増額": 80,
    "増配": 70,
    "特別配当": 60,
    "自己株式取得": 50,
    "自社株買い": 50,
    "黒字転換": 70,
    "過去最高": 60,
    "増益": 50,
}

TDNET_SELL_KEYWORDS: dict[str, int] = {
    "下方修正": -80,
    "業績予想の減額": -80,
    "減配": -60,
    "無配": -70,
    "赤字転落": -80,
    "赤字": -50,
    "特別損失": -50,
    "不祥事": -90,
    "訂正報告書": -40,
    "減益": -50,
}

# ---- ニュース キーワード ----

NEWS_BEAR_KEYWORDS: dict[str, int] = {
    # 日本語
    "利上げ": -50,
    "金利引き上げ": -50,
    "景気後退": -70,
    "リセッション": -70,
    "貿易摩擦": -40,
    "関税": -30,
    "破綻": -80,
    "倒産": -80,
    "暴落": -70,
    "急落": -50,
    # 英語（海外メディア用）
    "rate hike": -50,
    "recession": -70,
    "tariff": -30,
    "trade war": -40,
    "bankruptcy": -80,
    "crash": -70,
    "plunge": -60,
    "selloff": -50,
    "sell-off": -50,
    "downturn": -50,
    "default": -60,
    "inflation surge": -50,
    "bear market": -60,
}

NEWS_BULL_KEYWORDS: dict[str, int] = {
    # 日本語
    "利下げ": 50,
    "金融緩和": 50,
    "景気回復": 60,
    "過去最高": 50,
    "好決算": 60,
    "急騰": 50,
    "最高値": 60,
    # 英語（海外メディア用）
    "rate cut": 50,
    "rally": 50,
    "surge": 50,
    "record high": 60,
    "all-time high": 60,
    "bull market": 50,
    "earnings beat": 60,
    "stimulus": 50,
    "easing": 50,
    "recovery": 50,
}


def score_text(
    text: str,
    buy_kw: dict[str, int],
    sell_kw: dict[str, int],
) -> tuple[int, list[str]]:
    """
    テキストをキーワードスキャンしてスコアと一致キーワードを返す

    戻り値: (スコア, 一致キーワードのリスト)
    """
    score = 0
    matched = []
    text_lower = text.lower()

    for kw, s in buy_kw.items():
        if kw.lower() in text_lower:
            score += s
            matched.append(kw)

    for kw, s in sell_kw.items():
        if kw.lower() in text_lower:
            score += s  # sell_kw の値は負なので加算でOK
            matched.append(kw)

    return score, matched


def dispatch_tdnet(items: list[dict], config: dict, threshold: int = 40) -> int:
    """
    TDnet開示をスコアリングして、閾値以上のものを通知する

    戻り値: 送信件数
    """
    macro_signal = _get_macro_signal()
    sent = 0
    for item in items:
        score, matched = score_text(
            item["title"],
            TDNET_BUY_KEYWORDS,
            TDNET_SELL_KEYWORDS,
        )

        if abs(score) < threshold:
            continue

        signal = "BUY" if score > 0 else "SELL"
        icon = "🟢" if score > 0 else "🔴"
        kw_str = "、".join(matched) if matched else "-"
        hint = _build_hint(matched, score, macro_signal)

        message = (
            f"{icon} **[TDnet] {item['code']} {item['name']}**\n"
            f"  {item['title']}\n"
            f"  スコア: {score:+d} ({signal})  キーワード: {kw_str}\n"
            f"  示唆: {hint}\n"
            f"  {item['url']}"
        )
        notify(message, config)
        sent += 1

    return sent


# 海外ニュースの日本関連フィルタ
# これらを含む海外ニュースか、スコアが高い（グローバル影響大）もののみ通知
JAPAN_RELEVANCE_KEYWORDS: list[str] = [
    # 直接的な日本関連
    "japan", "japanese", "nikkei", "topix", "tokyo",
    "yen", "jpy", "boj", "bank of japan", "ueda",
    # 日本に波及しやすいテーマ
    "asia", "asian", "global", "worldwide",
    "fed", "federal reserve", "fomc", "powell",
    "china", "chinese", "beijing",
    "oil", "crude", "semiconductor", "chip",
    "supply chain", "trade war", "tariff",
]

# グローバル影響が大きい = 日本関連キーワード不要とみなすスコア閾値
GLOBAL_IMPACT_THRESHOLD = 50


def _is_japan_relevant(title: str, score: int) -> bool:
  """海外ニュースが日本市場に影響しそうか判定する"""
  # スコアが高い = グローバルに影響大 → 日本にも波及する
  if abs(score) >= GLOBAL_IMPACT_THRESHOLD:
    return True
  # 日本関連キーワードを含む
  title_lower = title.lower()
  return any(kw in title_lower for kw in JAPAN_RELEVANCE_KEYWORDS)


def _is_overseas_source(source: str) -> bool:
  """海外フィードかどうかを判定する（ASCII名 = 海外とみなす）"""
  return source.isascii()


def dispatch_news(items: list[dict], config: dict, threshold: int = 30) -> int:
    """
    ニュースをスコアリングして、閾値以上のものを通知する
    海外ニュースは日本市場への影響が見込まれるもののみ通知

    戻り値: 送信件数
    """
    macro_signal = _get_macro_signal()
    sent = 0
    for item in items:
        score, matched = score_text(
            item["title"],
            NEWS_BULL_KEYWORDS,
            NEWS_BEAR_KEYWORDS,
        )

        if abs(score) < threshold:
            continue

        # 海外ニュースは日本関連フィルタを通す
        if _is_overseas_source(item.get("source", "")) and not _is_japan_relevant(item["title"], score):
            continue

        signal = "強気" if score > 0 else "弱気"
        icon = "🟢" if score > 0 else "🔴"
        kw_str = "、".join(matched) if matched else "-"
        hint = _build_hint(matched, score, macro_signal)

        message = (
            f"{icon} **[NEWS] {item['title']}**\n"
            f"  スコア: {score:+d} ({signal})  キーワード: {kw_str}\n"
            f"  示唆: {hint}\n"
            f"  出典: {item['source']}  {item['url']}"
        )
        notify(message, config)
        sent += 1

    return sent
