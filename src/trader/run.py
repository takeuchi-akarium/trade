"""
自動売買 CLI

使い方:
  python src/trader/run.py --dry-run           # 注文なしで1サイクル実行
  python src/trader/run.py                     # 本番1サイクル
  python src/trader/run.py --daemon            # 常駐モード
  python src/trader/run.py --daemon --dry-run  # 常駐ドライラン
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

INTERVAL_SECONDS = {
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
}


def main():
  parser = argparse.ArgumentParser(description="BTC自動売買")
  parser.add_argument("--dry-run", action="store_true", help="注文を出さずに動作確認")
  parser.add_argument("--daemon", action="store_true", help="常駐モードで定期実行")
  parser.add_argument("--interval", default="1d", help="判定間隔 (1h, 4h, 1d)")
  args = parser.parse_args()

  from common.config_loader import load_config
  config = load_config()

  # config.yaml の dry_run 設定も尊重（CLIフラグが優先）
  dryRun = args.dry_run or config.get("trader", {}).get("dry_run", True)

  if dryRun:
    print("=" * 50)
    print("  ドライランモード（注文は実行しません）")
    print("=" * 50)

  from trader.engine import runCycle

  if args.daemon:
    pollSec = INTERVAL_SECONDS.get(args.interval, 86400)
    print(f"常駐モード: {args.interval} ({pollSec}秒間隔)")
    print("Ctrl+C で停止\n")

    try:
      while True:
        try:
          runCycle(config, dryRun=dryRun)
        except Exception as e:
          print(f"\n  エラー: {e}")
        time.sleep(pollSec)
    except KeyboardInterrupt:
      print("\n\n停止しました。")
  else:
    # 1回実行
    try:
      runCycle(config, dryRun=dryRun)
    except Exception as e:
      print(f"\nエラー: {e}")
      sys.exit(1)


if __name__ == "__main__":
  main()
