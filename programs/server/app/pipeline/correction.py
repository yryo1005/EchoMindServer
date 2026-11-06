"""文字起こし結果の文章校正モジュール．

Gemini APIを用いて，ASRの誤認識(句読点の欠落，助詞の誤り等)を軽微に修正する．
発言内容の意味を変える大幅な書き換えは行わない．
"""

from __future__ import annotations

from app.services.gemini_client import generate_text

_PROMPT_TEMPLATE = (
    "以下は音声認識によって文字起こしされた発言テキストです．"
    "意味を変えずに，誤字・脱字・句読点の誤りのみを修正した結果を出力してください．"
    "説明や前置きは不要で，修正後のテキストのみを出力してください．\n\n"
    "発言テキスト: {text}"
)


def correct_text(text: str) -> str:
    """文字起こし結果を文章校正する関数．

    引数:
        text (str): ASRによる文字起こし結果のテキスト
    戻り値:
        corrected_text (str): 校正後のテキスト
    """
    if not text.strip():
        return text
    prompt = _PROMPT_TEMPLATE.format(text=text)
    return generate_text(prompt).strip()
