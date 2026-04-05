"""
TDnet適時開示を irbank.net 経由で取得

TDnet本体（release.tdnet.info）はHTTPアクセスが制限されているため、
TDnetデータを集約している irbank.net を使用する。
"""

import time
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

BASE = "https://irbank.net/td"

# カテゴリ名 → URL パス
CATEGORIES = {
    "決算": f"{BASE}/{quote('決算')}",
    "配当": f"{BASE}/{quote('配当')}",
    "業績修正": f"{BASE}/{quote('業績修正')}",
}


def fetch_disclosures(categories: list[str] | None = None) -> list[dict]:
    """
    指定カテゴリの適時開示を取得。
    categories 未指定時は CATEGORIES の全カテゴリを対象にする。

    戻り値: [{"id", "code", "name", "title", "category", "url"}, ...]
    """
    targets = categories or list(CATEGORIES.keys())
    results = []

    for category in targets:
        url = CATEGORIES.get(category)
        if not url:
            print(f"  [TDnet] 未知のカテゴリ: {category}")
            continue
        try:
            items = _fetch_category(url, category)
            results.extend(items)
            time.sleep(1)  # レート制限（irbank.netへの過剰アクセスを避ける）
        except Exception as e:
            print(f"  [TDnet] {category}: 取得失敗 ({e})")

    # 複数カテゴリで同じ開示IDが出た場合の重複除去
    seen = set()
    unique = []
    for item in results:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    return unique


def _fetch_category(url: str, category: str) -> list[dict]:
    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_table(soup, category)


def _parse_table(soup: BeautifulSoup, category: str) -> list[dict]:
    """
    irbank.netのテーブルをパース
    想定構造: 日時 | 証券コード | 銘柄名 | タイトル
    """
    results = []

    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        try:
            # タイトルリンクから文書IDを取得（例: /7203/140120260403598379）
            title_a = cells[3].find("a")
            if not title_a:
                continue

            href = title_a.get("href", "")
            parts = href.strip("/").split("/")
            doc_id = parts[-1] if parts else ""
            if not doc_id.isdigit():
                continue

            # 証券コード
            code_a = cells[1].find("a")
            code = code_a.get_text(strip=True) if code_a else cells[1].get_text(strip=True)

            results.append({
                "id": doc_id,
                "code": code,
                "name": cells[2].get_text(strip=True),
                "title": title_a.get_text(strip=True),
                "category": category,
                "datetime_str": cells[0].get_text(strip=True),
                "url": f"https://irbank.net{href}",
            })
        except Exception:
            continue

    return results
