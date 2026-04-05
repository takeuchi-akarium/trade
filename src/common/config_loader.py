"""
config.yaml を読み込み、${ENV_VAR} を環境変数で置換して返す
"""

import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML が必要です: pip install pyyaml")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass  # python-dotenv 未インストール時はスキップ

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    target = Path(path) if path else _CONFIG_PATH
    if not target.exists():
        raise FileNotFoundError(f"config.yaml が見つかりません: {target}")

    text = target.read_text(encoding="utf-8")

    # ${VAR_NAME} を環境変数で置換（未定義の場合は空文字）
    text = re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), ""),
        text,
    )

    return yaml.safe_load(text)
