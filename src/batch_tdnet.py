"""
TDnet適時開示ポーリングバッチ

タスクスケジューラで15分ごとに実行する。
irbank.net から最新の適時開示を取得し、
買い/売りキーワードが含まれる新着開示のみDiscordに通知する。

使い方:
  python src/batch_tdnet.py           # 通常実行（通知あり）
  python src/batch_tdnet.py --dry-run # 通知せずprintのみ（動作確認用）
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
from datetime import datetime
from common.config_loader import load_config
from common.logger import log, cleanup
from common.dedup_cache import load as cache_load, save as cache_save, is_new
from signals.collectors.tdnet_collector import fetch_disclosures
from signals.alert_dispatcher import (
    dispatch_tdnet,
    score_text,
    TDNET_BUY_KEYWORDS,
    TDNET_SELL_KEYWORDS,
)

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_PATH = PROJECT_ROOT / "data/cache/tdnet_seen.json"


def run(dry_run: bool = False) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "[DRY RUN]" if dry_run else ""
    print(f"=== TDnet適時開示チェック: {now} {mode} ===")

    config = load_config()
    tdnet_cfg = config.get("tdnet", {})

    if not tdnet_cfg.get("enabled", True):
        print("tdnet.enabled = false のためスキップ")
        return

    categories = tdnet_cfg.get("categories", ["決算", "配当", "業績修正"])
    threshold = tdnet_cfg.get("score_threshold", 40)

    items = fetch_disclosures(categories)

    if not items:
        log("tdnet", "fetched:0 notified:0")
        return

    seen_ids = cache_load(CACHE_PATH)
    new_items = [item for item in items if is_new(seen_ids, item["id"])]

    sent = 0
    if new_items and not dry_run:
        sent = dispatch_tdnet(new_items, config, threshold)
    log("tdnet", f"fetched:{len(items)} new:{len(new_items)} notified:{sent}")

    for item in new_items:
        seen_ids.add(item["id"])
    cache_save(CACHE_PATH, seen_ids)
    cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TDnet適時開示バッチ")
    parser.add_argument("--dry-run", action="store_true", help="通知を送らずprintのみ")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
