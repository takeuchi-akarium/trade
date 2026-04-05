"""
簡易バッチログ

data/logs/batch_YYYY-MM-DD.log に1行ずつ追記する。
7日以上前のログは自動削除。
"""

from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent.parent / "data" / "logs"


def log(batch_name: str, message: str) -> None:
  """1行ログを追記"""
  LOG_DIR.mkdir(parents=True, exist_ok=True)
  today = datetime.now().strftime("%Y-%m-%d")
  log_file = LOG_DIR / f"batch_{today}.log"
  timestamp = datetime.now().strftime("%H:%M:%S")
  line = f"[{timestamp}] [{batch_name}] {message}\n"
  with open(log_file, "a", encoding="utf-8") as f:
    f.write(line)


def cleanup(days: int = 7) -> None:
  """古いログを削除"""
  if not LOG_DIR.exists():
    return
  cutoff = datetime.now() - timedelta(days=days)
  for f in LOG_DIR.glob("batch_*.log"):
    try:
      date_str = f.stem.replace("batch_", "")
      file_date = datetime.strptime(date_str, "%Y-%m-%d")
      if file_date < cutoff:
        f.unlink()
    except ValueError:
      pass
