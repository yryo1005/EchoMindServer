"""文字起こし結果の文章校正モジュール．

Gemini APIを用いて，ASRの誤認識(句読点の欠落，助詞の誤り等)を軽微に修正する．
発言内容の意味を変える大幅な書き換えは行わない．

1発言ごとにGemini APIを呼び出すとAPIコール数(トークン消費)が発話数に比例して
増えてしまうため，1つの会話に含まれる全発言をまとめて1回のAPI呼び出しで校正する．
"""

from __future__ import annotations

import re

from app.services.gemini_client import generate_text

_BATCH_PROMPT_TEMPLATE = (
    "以下は音声認識によって文字起こしされた，複数の発言テキストです．"
    "各発言について，意味を変えずに誤字・脱字・句読点の誤りのみを修正してください．"
    "入力と同じ件数・同じ順序で，各行を「番号. 修正後のテキスト」の形式のみで出力してください．"
    "説明や前置きは不要です．\n\n"
    "{numbered_texts}"
)

_LINE_PATTERN = re.compile(r"^\s*(\d+)\s*[.．]\s*(.*)$")


def correct_texts(texts: list[str]) -> list[str]:
    """複数の文字起こし結果をまとめて1回のGemini API呼び出しで文章校正する関数．

    引数:
        texts (list[str]): ASRによる文字起こし結果のテキストのリスト(1会話分)
    戻り値:
        corrected_texts (list[str]): 校正後のテキストのリスト(texts と同じ順序・件数)
    """
    if not texts:
        return []

    non_empty_indices = [i for i, text in enumerate(texts) if text.strip()]
    if not non_empty_indices:
        return list(texts)

    numbered_texts = "\n".join(f"{i + 1}. {texts[i]}" for i in non_empty_indices)
    prompt = _BATCH_PROMPT_TEMPLATE.format(numbered_texts=numbered_texts)
    response = generate_text(prompt)

    corrected = list(texts)
    if not response:
        # Gemini APIが空応答(安全性フィルタ等)を返した場合は，校正前のテキストをそのまま用いる
        return corrected

    for line in response.splitlines():
        match = _LINE_PATTERN.match(line)
        if match is None:
            continue
        index = int(match.group(1)) - 1
        if 0 <= index < len(texts):
            corrected[index] = match.group(2).strip()

    return corrected
