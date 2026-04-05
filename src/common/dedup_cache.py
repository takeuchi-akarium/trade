"""
重複排除キャッシュ（JSONファイルベース）

同じ開示・ニュースを複数回通知しないための既送信ID管理。
"""

import json
from pathlib import Path


def load(path: str | Path) -> set[str]:
    """キャッシュファイルからIDセットを読み込む。ファイルがなければ空セット。"""
    p = Path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return set(data.get("seen_ids", []))
    except Exception:
        return set()


def save(path: str | Path, seen_ids: set[str], max_size: int = 1000) -> None:
    """IDセットをファイルに保存。max_size 件を超えたら古い方から削除。"""
    from datetime import datetime

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    ids_list = list(seen_ids)
    if len(ids_list) > max_size:
        ids_list = ids_list[-max_size:]

    p.write_text(
        json.dumps(
            {"seen_ids": ids_list, "last_updated": datetime.now().isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )


def is_new(seen_ids: set[str], item_id: str) -> bool:
    """IDが未送信（キャッシュに存在しない）かどうか"""
    return item_id not in seen_ids
