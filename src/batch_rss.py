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
from common.logger import log, cleanup
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

    items = fetch_news(feeds)

    if not items:
        log("rss", "fetched:0 notified:0")
        return

    seen_ids = cache_load(CACHE_PATH)
    new_items = [item for item in items if is_new(seen_ids, item["id"])]

    sent = 0
    if new_items and not dry_run:
        sent = dispatch_news(new_items, config, threshold)
    log("rss", f"fetched:{len(items)} new:{len(new_items)} notified:{sent}")

    for item in new_items:
        seen_ids.add(item["id"])
    cache_save(CACHE_PATH, seen_ids, max_size=500)
    cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RSSニュースバッチ")
    parser.add_argument("--dry-run", action="store_true", help="通知を送らずprintのみ")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
