"""
15分バッチ: マクロ指標収集 → スコアリング → シグナル判定 → 通知

タスクスケジューラで15分ごとに実行する。
シグナルが前回から変化したときのみ通知を送る（通知疲れ防止）。
"""

import sys
from pathlib import Path

# src/ をモジュール検索パスに追加
sys.path.insert(0, str(Path(__file__).parent))

import json
from datetime import datetime
from common.config_loader import load_config
from common.notifier import notify
from signals.aggregator import collect_and_score, to_signal

PROJECT_ROOT = Path(__file__).parent.parent
LATEST_SIGNAL_PATH = PROJECT_ROOT / "data/signals/latest_signal.json"


def run() -> None:
    config = load_config()
    sig_cfg = config.get("signal", {})
    weights = sig_cfg.get("weights")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== シグナル収集: {now} ===")

    result = collect_and_score(weights)
    total = result["total"]
    signal = to_signal(
        total,
        buy_threshold=sig_cfg.get("buy_threshold", 30),
        sell_threshold=sig_cfg.get("sell_threshold", -30),
    )

    print(f"スコア: {total:+d}  →  シグナル: {signal}")
    for k, v in result["details"].items():
        score_str = f"{result['scores'][k]:+d}" if k in result["scores"] else "N/A"
        print(f"  {k:<15}: {v:<25} (score: {score_str})")

    # シグナルが変化したときだけ通知
    prev_signal = _load_prev_signal()
    if signal != prev_signal:
        icon = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        lines = [f"{icon} **[MACRO] シグナル変化: {prev_signal} → {signal}**  (スコア: {total:+d})"]
        for k, v in result["details"].items():
            score_str = f"{result['scores'][k]:+d}" if k in result["scores"] else "N/A"
            lines.append(f"  {k}: {v}  ({score_str})")
        message = "\n".join(lines)
        print("\n通知送信中...")
        notify(message, config)
    else:
        print("(シグナル変化なし → 通知スキップ)")

    # 最新シグナルを保存
    LATEST_SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_SIGNAL_PATH.write_text(
        json.dumps(
            {
                "signal": signal,
                "total": total,
                "scores": result["scores"],
                "details": result["details"],
                "updated_at": datetime.now().isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n最新シグナル保存: {LATEST_SIGNAL_PATH}")


def _load_prev_signal() -> str:
    if LATEST_SIGNAL_PATH.exists():
        try:
            return json.loads(LATEST_SIGNAL_PATH.read_text(encoding="utf-8")).get("signal", "HOLD")
        except Exception:
            pass
    return "HOLD"


if __name__ == "__main__":
    run()
