"""
トレード判断記録（Trade Journal）

板情報・ニュース・テクニカル・判断理由を記録し、
結果と照合してパターン認識を蓄積するためのCLI。

Usage:
  python src/trade_journal.py add --ticker 8035 --direction short
  python src/trade_journal.py result --id 20260413_8035 --entry 44000 --exit 42590 --outcome win
  python src/trade_journal.py list
  python src/trade_journal.py stats
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "trade_journal"
ENTRIES_FILE = DATA_DIR / "entries.json"

JST = timezone(timedelta(hours=9))


def loadEntries():
  if not ENTRIES_FILE.exists():
    return []
  with open(ENTRIES_FILE, "r", encoding="utf-8") as f:
    return json.load(f)


def saveEntries(entries):
  DATA_DIR.mkdir(parents=True, exist_ok=True)
  with open(ENTRIES_FILE, "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=2)


def generateId(date, ticker):
  return f"{date.replace('-', '')}_{ticker}"


def addEntry(ticker, direction, name="", preMarket=None, technicals=None, news=None, reasoning=""):
  entries = loadEntries()
  now = datetime.now(JST)
  date = now.strftime("%Y-%m-%d")
  entryId = generateId(date, ticker)

  # 同日・同銘柄の重複チェック
  existing = [e for e in entries if e["id"] == entryId]
  if existing:
    # サフィックス追加
    count = len([e for e in entries if e["id"].startswith(entryId)])
    entryId = f"{entryId}_{count + 1}"

  entry = {
    "id": entryId,
    "date": date,
    "ticker": ticker,
    "name": name,
    "direction": direction,
    "status": "open",
    "pre_market": preMarket or {},
    "technicals": technicals or {},
    "news": news or [],
    "reasoning": reasoning,
    "result": {
      "entry_price": None,
      "exit_price": None,
      "pnl_pct": None,
      "outcome": None,
      "notes": "",
    },
    "created_at": now.isoformat(),
    "updated_at": now.isoformat(),
  }

  entries.append(entry)
  saveEntries(entries)
  return entry


def updateResult(entryId, entryPrice=None, exitPrice=None, outcome=None, notes=""):
  entries = loadEntries()
  found = None
  for e in entries:
    if e["id"] == entryId:
      found = e
      break

  if not found:
    print(f"エントリ '{entryId}' が見つかりません")
    return None

  if entryPrice is not None:
    found["result"]["entry_price"] = entryPrice
  if exitPrice is not None:
    found["result"]["exit_price"] = exitPrice
  if outcome is not None:
    found["result"]["outcome"] = outcome
    found["status"] = "closed"
  if notes:
    found["result"]["notes"] = notes

  # 損益計算
  ep = found["result"]["entry_price"]
  xp = found["result"]["exit_price"]
  if ep and xp:
    if found["direction"] == "short":
      found["result"]["pnl_pct"] = round((ep - xp) / ep * 100, 2)
    else:
      found["result"]["pnl_pct"] = round((xp - ep) / ep * 100, 2)

  found["updated_at"] = datetime.now(JST).isoformat()
  saveEntries(entries)
  return found


def listEntries(limit=20, status=None):
  entries = loadEntries()
  if status:
    entries = [e for e in entries if e["status"] == status]
  return entries[-limit:]


def calcStats():
  entries = loadEntries()
  closed = [e for e in entries if e["status"] == "closed"]

  if not closed:
    return {"total": len(entries), "closed": 0, "message": "まだクローズ済みの記録がありません"}

  wins = [e for e in closed if e["result"]["outcome"] == "win"]
  losses = [e for e in closed if e["result"]["outcome"] == "loss"]
  pnls = [e["result"]["pnl_pct"] for e in closed if e["result"]["pnl_pct"] is not None]

  stats = {
    "total": len(entries),
    "closed": len(closed),
    "open": len(entries) - len(closed),
    "wins": len(wins),
    "losses": len(losses),
    "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
    "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
    "max_win": round(max(pnls), 2) if pnls else 0,
    "max_loss": round(min(pnls), 2) if pnls else 0,
  }

  # 板偏り別の勝率
  highRatio = [e for e in closed if e.get("pre_market", {}).get("ask_bid_ratio", 0) >= 5]
  if highRatio:
    hrWins = [e for e in highRatio if e["result"]["outcome"] == "win"]
    stats["high_ratio_trades"] = len(highRatio)
    stats["high_ratio_win_rate"] = round(len(hrWins) / len(highRatio) * 100, 1)

  # 方向別
  for d in ["long", "short"]:
    dTrades = [e for e in closed if e["direction"] == d]
    if dTrades:
      dWins = [e for e in dTrades if e["result"]["outcome"] == "win"]
      stats[f"{d}_trades"] = len(dTrades)
      stats[f"{d}_win_rate"] = round(len(dWins) / len(dTrades) * 100, 1)

  return stats


def formatEntry(e):
  """エントリを表示用にフォーマット"""
  dirMark = "[SHORT]" if e["direction"] == "short" else "[LONG]"
  status = "[OPEN]" if e["status"] == "open" else "[CLOSED]"
  lines = [
    f"  [{e['id']}] {e['date']} {e.get('name', '')}({e['ticker']}) {dirMark} {status}",
  ]

  pm = e.get("pre_market", {})
  if pm.get("ask_bid_ratio"):
    lines.append(f"    板: 売/買={pm['ask_bid_ratio']:.1f}x (売{pm.get('ask_volume', '?')} / 買{pm.get('bid_volume', '?')})")

  tech = e.get("technicals", {})
  if tech.get("close"):
    parts = [f"終値{tech['close']:,}"]
    if tech.get("bb_position"):
      parts.append(f"BB:{tech['bb_position']}")
    if tech.get("rsi"):
      parts.append(f"RSI:{tech['rsi']}")
    lines.append(f"    テクニカル: {' / '.join(parts)}")

  if e.get("news"):
    lines.append(f"    ニュース: {' | '.join(e['news'][:3])}")

  if e.get("reasoning"):
    lines.append(f"    判断理由: {e['reasoning'][:80]}")

  r = e.get("result", {})
  if r.get("outcome"):
    mark = "[WIN]" if r["outcome"] == "win" else "[LOSS]"
    lines.append(f"    結果: {mark} {r['outcome'].upper()} ({r.get('pnl_pct', 0):+.2f}%) {r.get('entry_price', '')}→{r.get('exit_price', '')}")

  return "\n".join(lines)


def cmdAdd(args):
  preMarket = {}
  if args.ask_volume is not None:
    preMarket["ask_volume"] = args.ask_volume
  if args.bid_volume is not None:
    preMarket["bid_volume"] = args.bid_volume
  if preMarket.get("ask_volume") and preMarket.get("bid_volume") and preMarket["bid_volume"] > 0:
    preMarket["ask_bid_ratio"] = round(preMarket["ask_volume"] / preMarket["bid_volume"], 1)
  if args.board_notes:
    preMarket["notes"] = args.board_notes
  if args.screenshot:
    preMarket["screenshot"] = args.screenshot

  technicals = {}
  if args.close is not None:
    technicals["close"] = args.close
  if args.bb:
    technicals["bb_position"] = args.bb
  if args.rsi is not None:
    technicals["rsi"] = args.rsi
  if args.macd:
    technicals["macd"] = args.macd
  if args.tech_notes:
    technicals["notes"] = args.tech_notes

  news = args.news.split("|") if args.news else []

  entry = addEntry(
    ticker=args.ticker,
    direction=args.direction,
    name=args.name or "",
    preMarket=preMarket,
    technicals=technicals,
    news=news,
    reasoning=args.reasoning or "",
  )
  print(f"[OK] 記録追加: {entry['id']}")
  print(formatEntry(entry))


def cmdResult(args):
  entry = updateResult(
    entryId=args.id,
    entryPrice=args.entry,
    exitPrice=args.exit,
    outcome=args.outcome,
    notes=args.notes or "",
  )
  if entry:
    print(f"[OK] 結果更新: {entry['id']}")
    print(formatEntry(entry))


def cmdList(args):
  entries = listEntries(limit=args.limit, status=args.status)
  if not entries:
    print("記録がありません")
    return

  print(f"=== Trade Journal ({len(entries)}件) ===\n")
  for e in entries:
    print(formatEntry(e))
    print()


def cmdStats(args):
  stats = calcStats()
  if stats.get("message"):
    print(stats["message"])
    return

  print("=== Trade Journal 統計 ===\n")
  print(f"  総記録: {stats['total']}件 (クローズ{stats['closed']} / オープン{stats['open']})")
  print(f"  勝敗: {stats['wins']}勝 {stats['losses']}敗 (勝率{stats['win_rate']}%)")
  print(f"  平均損益: {stats['avg_pnl']:+.2f}%")
  print(f"  最大利益: {stats['max_win']:+.2f}% / 最大損失: {stats['max_loss']:+.2f}%")

  if stats.get("high_ratio_trades"):
    print(f"\n  板偏り大(>=5x): {stats['high_ratio_trades']}件 / 勝率{stats['high_ratio_win_rate']}%")

  for d in ["long", "short"]:
    if stats.get(f"{d}_trades"):
      label = "ロング" if d == "long" else "ショート"
      print(f"  {label}: {stats[f'{d}_trades']}件 / 勝率{stats[f'{d}_win_rate']}%")


def main():
  parser = argparse.ArgumentParser(description="トレード判断記録")
  sub = parser.add_subparsers(dest="command")

  # add
  p_add = sub.add_parser("add", help="新規記録")
  p_add.add_argument("--ticker", required=True, help="銘柄コード (例: 8035)")
  p_add.add_argument("--direction", required=True, choices=["long", "short"])
  p_add.add_argument("--name", help="銘柄名")
  p_add.add_argument("--ask-volume", type=int, help="売り板合計株数")
  p_add.add_argument("--bid-volume", type=int, help="買い板合計株数")
  p_add.add_argument("--board-notes", help="板の特記事項")
  p_add.add_argument("--screenshot", help="板スクリーンショットのパス")
  p_add.add_argument("--close", type=float, help="直近終値")
  p_add.add_argument("--bb", help="BB位置 (例: +2σ〜+3σ)")
  p_add.add_argument("--rsi", type=float, help="RSI値")
  p_add.add_argument("--macd", help="MACDの状態")
  p_add.add_argument("--tech-notes", help="テクニカル特記事項")
  p_add.add_argument("--news", help="関連ニュース (|区切り)")
  p_add.add_argument("--reasoning", help="判断理由")

  # result
  p_res = sub.add_parser("result", help="結果記入")
  p_res.add_argument("--id", required=True, help="エントリID")
  p_res.add_argument("--entry", type=float, help="エントリー価格")
  p_res.add_argument("--exit", type=float, help="イグジット価格")
  p_res.add_argument("--outcome", choices=["win", "loss", "even"])
  p_res.add_argument("--notes", help="結果メモ")

  # list
  p_list = sub.add_parser("list", help="一覧表示")
  p_list.add_argument("--limit", type=int, default=20)
  p_list.add_argument("--status", choices=["open", "closed"])

  # stats
  sub.add_parser("stats", help="統計表示")

  args = parser.parse_args()
  if args.command == "add":
    cmdAdd(args)
  elif args.command == "result":
    cmdResult(args)
  elif args.command == "list":
    cmdList(args)
  elif args.command == "stats":
    cmdStats(args)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
