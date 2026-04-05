"""
RSSニュースポーリングバッチ

タスクスケジューラで30分ごとに実行する。
Yahoo!ビジネス・NHK経済などのRSSから新着ニュースを取得し、
株価影響キーワードが含まれるものだけDiscordに通知する。

使い方:
  python src/batch_rss.py           # 通常実行（通知あり）
  python src/batch_rss.py --dry-run # 通知せずprintのみ（動作確認用）
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
from datetime import datetime
from common.config_loader import load_config
from common.dedup_cache import load as cache_load, save as cache_save, is_new
from signals.collectors.rss_collector import fetch_news, DEFAULT_FEEDS
from signals.alert_dispatcher import (
    dispatch_news,
    score_text,
    NEWS_BULL_KEYWORDS,
    NEWS_BEAR_KEYWORDS,
    _is_overseas_source,
    _is_japan_relevant,
)

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_PATH = PROJECT_ROOT / "data/cache/rss_seen.json"


def run(dry_run: bool = False) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "[DRY RUN]" if dry_run else ""
    print(f"=== RSSニュースチェック: {now} {mode} ===")

    config = load_config()
    rss_cfg = config.get("rss", {})

    if not rss_cfg.get("enabled", True):
        print("rss.enabled = false のためスキップ")
        return

    feeds = rss_cfg.get("feeds", DEFAULT_FEEDS)
    threshold = rss_cfg.get("score_threshold", 30)

    # ニュース取得
    print(f"フィード数: {len(feeds)}")
    items = fetch_news(feeds)
    print(f"取得件数: {len(items)}")

    if not items:
        print("ニュースなし")
        return

    # 新着フィルタ
    seen_ids = cache_load(CACHE_PATH)
    new_items = [item for item in items if is_new(seen_ids, item["id"])]
    print(f"新着: {len(new_items)} 件（既読: {len(items) - len(new_items)} 件スキップ）\n")

    if not new_items:
        print("新着なし → スキップ")
        return

    # スコアリング結果を表示
    for item in new_items:
        score, matched = score_text(item["title"], NEWS_BULL_KEYWORDS, NEWS_BEAR_KEYWORDS)
        flag = "★" if abs(score) >= threshold else "  "
        signal = "強気" if score > 0 else "弱気" if score < 0 else "中立"
        kw = "、".join(matched) if matched else "-"
        overseas = _is_overseas_source(item.get("source", ""))
        relevant = _is_japan_relevant(item["title"], score) if overseas else True
        skip_tag = " [skip:JP関連なし]" if overseas and not relevant else ""
        if matched:  # キーワード一致したものだけ表示
            print(f"{flag} {item['title']}")
            print(f"     score:{score:+d}({signal})  kw:{kw}  src:{item['source']}{skip_tag}")

    # 通知（dry_run時はスキップ）
    if not dry_run:
        print("\n通知送信中...")
        sent = dispatch_news(new_items, config, threshold)
        print(f"通知送信: {sent} 件")
    else:
        print("\n[DRY RUN] 通知はスキップ")

    # キャッシュ更新
    for item in new_items:
        seen_ids.add(item["id"])
    cache_save(CACHE_PATH, seen_ids, max_size=500)  # RSSは件数が多いので上限小さめ
    print(f"キャッシュ更新: {CACHE_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RSSニュースバッチ")
    parser.add_argument("--dry-run", action="store_true", help="通知を送らずprintのみ")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
