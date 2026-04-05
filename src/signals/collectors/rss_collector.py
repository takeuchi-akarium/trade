"""
RSSフィードからニュースを収集（標準ライブラリのみ使用）

対応フォーマット: RSS 2.0
"""

import xml.etree.ElementTree as ET
import requests

DEFAULT_FEEDS = [
    {
        "url": "https://news.yahoo.co.jp/rss/topics/business.xml",
        "name": "Yahoo!ビジネス",
    },
    {
        "url": "https://www3.nhk.or.jp/rss/news/cat7.xml",
        "name": "NHK経済",
    },
]


def fetch_news(feeds: list[dict] | None = None) -> list[dict]:
    """
    RSSフィードからニュースアイテムを取得

    戻り値: [{"id", "title", "url", "pubdate", "source"}, ...]
    id には URL を使う（重複排除キー）
    """
    targets = feeds or DEFAULT_FEEDS
    results = []

    for feed in targets:
        try:
            items = _fetch_feed(feed["url"], feed["name"])
            results.extend(items)
        except Exception as e:
            print(f"  [RSS] {feed['name']}: 取得失敗 ({e})")

    return results


def _fetch_feed(url: str, source_name: str) -> list[dict]:
    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    results = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        if not title or not link:
            continue

        results.append({
            "id": link,
            "title": title,
            "url": link,
            "pubdate": pub_date,
            "source": source_name,
        })

    return results
