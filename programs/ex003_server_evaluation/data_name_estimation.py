"""名前推定の精度検証用テストケースを生成するモジュール．

音声合成(TTS)が利用できないため，この検証はASRより後段のロジック(会話テキストから
Gemini APIで名前を推定する処理)に限定する．Gemini APIを用いて，自己紹介や呼びかけ等の
名前の手がかりを含む疑似会話テキストと，その正解の名前を生成する．
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from google import genai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

OUTPUT_PATH = Path("datasets/ex003_server_evaluation/name_estimation_cases.json")
N_CASES = 20


def _load_gemini_api_key() -> str:
    """tokens.jsonからGemini APIキーを読み込む関数．"""
    with open("tokens.json", encoding="utf-8") as f:
        return json.load(f)["gemini"]


_GENERATION_PROMPT = """日本語の複数人(2〜3人)による自然な会話を作成してください．
会話の中で，対象人物(発言者の1人)の名前が，自己紹介または他の人物からの呼びかけによって
会話内に明示される，または(より難しい場合として)暗示的に推測できるようにしてください．
対象人物以外の発言には名前の手がかりは含めないでください．

以下のJSON形式のみを出力してください(他の説明文は一切不要です)．
{{
  "target_name": "対象人物の名前(姓または姓名，呼称の敬称は含めない)",
  "difficulty": "easy または hard",
  "lines": [
    {{"speaker": "A", "text": "発言内容", "is_target": true または false}},
    ...
  ]
}}

"easy"は自己紹介等で名前が明示される場合，"hard"は名前が直接言われず，
会話の流れ(例: 他の人物が「〇〇さんは〇〇が得意だよね」と話す等)から推測が必要な場合とします．
今回は{difficulty}な難易度のケースを1つ作成してください．発言数は8〜14程度にしてください．
"""


@retry(retry=retry_if_exception_type(Exception), wait=wait_random_exponential(multiplier=2, max=60), stop=stop_after_attempt(6))
def _generate_case(client: genai.Client, difficulty: str) -> dict:
    """1件の名前推定テストケースをGemini APIで生成する関数．

    引数:
        client (genai.Client): Gemini APIクライアント
        difficulty (str): "easy" または "hard"
    戻り値:
        case (dict): target_name, difficulty, linesを含むテストケース
    """
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=_GENERATION_PROMPT.format(difficulty=difficulty),
    )
    text = response.text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"JSON形式の抽出に失敗しました: {text}")
    return json.loads(match.group(0))


def build_name_estimation_cases() -> list[dict]:
    """名前推定の精度検証用テストケースを生成する関数．

    引数:
        なし
    戻り値:
        cases (list[dict]): 生成されたテストケースのリスト
    """
    client = genai.Client(api_key=_load_gemini_api_key())

    cases = []
    for i in range(N_CASES):
        difficulty = "easy" if i % 2 == 0 else "hard"
        case = _generate_case(client, difficulty)
        cases.append(case)
        time.sleep(4.5)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    return cases


if __name__ == "__main__":
    cases = build_name_estimation_cases()
    print(f"{len(cases)}件のテストケースを {OUTPUT_PATH} に生成しました．")
