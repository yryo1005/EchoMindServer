"""名前推定の精度検証スクリプト．

`data_name_estimation.py`で生成したテストケースに対し，サーバーが実際に使用している
名前推定ロジック(`app/pipeline/person_identification.estimate_name_from_context`)を適用し，
推定された名前が正解と一致するかを評価する．
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from app.pipeline.person_identification import estimate_name_from_context  # noqa: E402

CASES_PATH = Path("datasets/ex003_server_evaluation/name_estimation_cases.json")
OUTPUT_DIR = Path("outputs/ex003_server_evaluation/name_estimation")


def _build_context_lines(case: dict) -> list[str]:
    """テストケースの発言リストから，名前推定関数に渡すコンテキスト行を構築する関数．

    引数:
        case (dict): "lines"キーに発言リストを持つテストケース
    戻り値:
        context_lines (list[str]): 対象人物の発言に"[対象人物]"を付与した発言リスト
    """
    return [
        f"{'[対象人物]' if line['is_target'] else ''}{line['text']}" for line in case["lines"]
    ]


def _is_correct(estimated_name: str, true_name: str) -> bool:
    """推定された名前が正解と一致するかを判定する関数．

    敬称(さん等)や完全な表記ゆれを許容するため，部分一致で判定する．

    引数:
        estimated_name (str): 推定された名前
        true_name (str): 正解の名前
    戻り値:
        is_correct (bool): 正解とみなせるかどうか
    """
    if estimated_name in ("", "不明"):
        return False
    return true_name in estimated_name or estimated_name in true_name


def main() -> None:
    """全テストケースに対して名前推定を実行し，精度を評価する関数．

    引数:
        なし
    戻り値:
        なし
    """
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    records = []
    for case in cases:
        context_lines = _build_context_lines(case)
        estimated_name = estimate_name_from_context(context_lines)
        is_correct = _is_correct(estimated_name, case["target_name"])
        records.append(
            {
                "difficulty": case["difficulty"],
                "true_name": case["target_name"],
                "estimated_name": estimated_name,
                "is_correct": is_correct,
            }
        )

    overall_accuracy = sum(r["is_correct"] for r in records) / len(records)
    accuracy_by_difficulty = {}
    for difficulty in ("easy", "hard"):
        subset = [r for r in records if r["difficulty"] == difficulty]
        if subset:
            accuracy_by_difficulty[difficulty] = sum(r["is_correct"] for r in subset) / len(subset)

    metrics = {
        "overall_accuracy": overall_accuracy,
        "accuracy_by_difficulty": accuracy_by_difficulty,
        "n_cases": len(records),
        "records": records,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print("overall_accuracy =", overall_accuracy, "accuracy_by_difficulty =", accuracy_by_difficulty)


if __name__ == "__main__":
    main()
