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
    # TOB/MBO（被買付側）
    "TOB対象":        "公開買付けの対象銘柄。買付価格へのプレミアム鞘寄せで株価上昇が見込まれる",
    "MBO対象":        "MBO対象銘柄。買付価格へ株価が収斂する。応募か市場売却かの判断が必要",
    "株式交換対象":   "株式交換で親会社株に転換。交換比率に基づく理論価格へ鞘寄せが進む",
    # TOB/MBO（買付側）
    "TOB実施側":      "買収コスト負担で短期的には売られやすい。中長期ではシナジー次第",
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

# ---- TOB/MBO 判定 ----

import re

# HD/ホールディングスなど略称・正式名の表記揺れ置換テーブル
_NAME_NORMALIZE = [
    ("ホールディングス", "HD"),
    ("フィナンシャルグループ", "FG"),
    ("グループ", "G"),
    ("　", ""),
    (" ", ""),
]


def _name_matches(company_name: str, text_part: str, title: str) -> bool:
  """
  irbank上の企業名と、タイトル中の企業表記が同一企業を指すか判定する。

  HD ↔ ホールディングス等の表記揺れや、タイトル中の(株)○○からの
  正式名抽出も考慮する。
  """
  # 直接一致
  if company_name in text_part or text_part in company_name:
    return True

  # 正規化して比較（HD ↔ ホールディングス等）
  def normalize(s: str) -> str:
    for old, new in _NAME_NORMALIZE:
      s = s.replace(old, new)
    return s

  norm_name = normalize(company_name)
  norm_part = normalize(text_part)
  if norm_name in norm_part or norm_part in norm_name:
    return True

  # タイトルから (株)○○ で始まる正式企業名を抽出し、一致する方を探す
  corp_names = re.findall(r"[(（]株[)）]([^(（と]+)", title)
  for corp in corp_names:
    corp = corp.strip()
    norm_corp = normalize(corp)
    if norm_name in norm_corp or norm_corp in norm_name:
      # この正式名がtext_part内に含まれていればマッチ
      if corp in text_part or normalize(corp) in norm_part:
        return True

  # タイトル中の「正式名(略称)」のペアから、text_partが略称にマッチするか確認
  # 例: 「パン・パシフィック・インターナショナルホールディングス(PPIH)」
  alias_pairs = re.findall(r"([^(（、と]+?)[(（]([^)）株]+?)[)）]", title)
  for full, alias in alias_pairs:
    full = full.strip()
    alias = alias.strip()
    # text_partが略称と一致 or 含まれる
    if alias == text_part or alias in text_part or text_part in alias:
      # その正式名が企業名とマッチするか
      norm_full = normalize(full)
      if norm_name in norm_full or norm_full in norm_name:
        return True

  return False


# TOBの文脈を示すキーワード
_TOB_CONTEXT = ["公開買付", "TOB", "MBO", "株式交換", "完全子会社化", "非公開化", "スクイーズアウト"]

# 被買付側（ターゲット）を示すキーワード — 強い買いシグナル
_TOB_TARGET_MARKERS = ["意見表明", "応募推奨", "賛同", "応募契約"]

# 買付側（アクワイアラー）を示すキーワード — 中立〜やや弱気
_TOB_ACQUIRER_MARKERS = ["開始に関する", "取得に関する", "子会社化を目的"]


def classify_tob(title: str, company_name: str = "") -> tuple[str | None, int, list[str]]:
  """
  開示タイトルからTOB/MBO関連かを判定し、役割とスコアを返す

  company_name を渡すと、株式交換など同一タイトルで両社が開示するケースで
  買付側/被買付側を正確に判別できる。

  戻り値: (role, score, matched_keywords)
    role: "target"（被買付側）/ "acquirer"（買付側）/ None（TOB無関係）
  """
  title_lower = title.lower()

  # TOBの文脈キーワードがなければ無関係
  has_context = any(kw.lower() in title_lower for kw in _TOB_CONTEXT)
  if not has_context:
    return None, 0, []

  # 被買付側の判定（ターゲット企業）
  is_target = any(kw in title for kw in _TOB_TARGET_MARKERS)
  if is_target:
    if "株式交換" in title:
      return "target", 85, ["株式交換対象"]
    if "MBO" in title_lower:
      return "target", 90, ["MBO対象"]
    return "target", 90, ["TOB対象"]

  # 「当社株式に対する」→ 被買付側（他社が当社をTOBしている）
  if "当社株式に対する" in title or "当社株式についての" in title:
    return "target", 90, ["TOB対象"]

  # 買付側の判定（アクワイアラー企業）
  is_acquirer = any(kw in title for kw in _TOB_ACQUIRER_MARKERS)
  if is_acquirer:
    return "acquirer", -20, ["TOB実施側"]

  # 株式交換・完全子会社化 — タイトルと企業名で役割を判別
  if ("子会社化" in title or "子会社異動" in title) and company_name:
    # 「当社の完全子会社化」→ 開示企業がターゲット
    if "当社の完全子会社化" in title or "当社の子会社化" in title:
      return "target", 85, ["株式交換対象"]

    # 「○○の子会社異動」→ ○○がアクワイアラー
    # 開示企業名（正式名・略称）がタイトル中で「の子会社異動」の直前に出ていたら買付側
    import re
    # 「○○の子会社異動」の直前の企業名/略称だけを抽出（貪欲マッチで最短ではなく最後の区切りから）
    acquirer_match = re.search(r"(?:及び|並びに|、)(.+?)の子会社異動", title)
    if not acquirer_match:
      acquirer_match = re.search(r"([^と、]+)の子会社異動", title)
    if acquirer_match:
      acquirer_part = acquirer_match.group(1).strip()
      if _name_matches(company_name, acquirer_part, title):
        return "acquirer", -20, ["TOB実施側"]
      return "target", 85, ["株式交換対象"]

    if f"{company_name}の子会社化" in title:
      return "acquirer", -20, ["TOB実施側"]

    # 「○○の完全子会社化」で○○が開示企業名と異なる → 開示企業は買付側
    m = re.search(r"(.+?)の完全子会社化", title)
    if m:
      subsidiary_name = m.group(1)
      if _name_matches(company_name, subsidiary_name, title):
        return "target", 85, ["株式交換対象"]
      else:
        return "acquirer", -20, ["TOB実施側"]

    # 上記で判定できなければ被買付側と推定
    return "target", 85, ["株式交換対象"]

  # 文脈はあるが役割不明
  if "MBO" in title_lower:
    return "target", 90, ["MBO対象"]
  return "target", 80, ["TOB対象"]


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
        # 通常キーワードスコアリング
        score, matched = score_text(
            item["title"],
            TDNET_BUY_KEYWORDS,
            TDNET_SELL_KEYWORDS,
        )

        # TOB/MBO判定 — 該当すればスコアと一致キーワードを上書き
        tob_role, tob_score, tob_kws = classify_tob(item["title"], item.get("name", ""))
        if tob_role is not None:
            # 無配などの売りキーワードはTOB文脈では無意味なので除去して再計算
            score = tob_score
            matched = tob_kws

        if abs(score) < threshold:
            continue

        signal = "BUY" if score > 0 else "SELL"
        icon = "🟢" if score > 0 else "🔴"
        kw_str = "、".join(matched) if matched else "-"
        hint = _build_hint(matched, score, macro_signal)

        # TOB/MBOの場合は役割を明示
        if tob_role == "target":
            role_tag = "📌被買付（買いチャンス）"
        elif tob_role == "acquirer":
            role_tag = "📌買付側（様子見）"
        else:
            role_tag = ""

        role_line = f"  {role_tag}\n" if role_tag else ""

        message = (
            f"{icon} **[TDnet] {item['code']} {item['name']}**\n"
            f"  {item['title']}\n"
            f"{role_line}"
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
