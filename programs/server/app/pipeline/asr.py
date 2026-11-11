"""音声認識(ASR)モジュール．

仕様書記載・ベンチマーク(.reports/report_002.md)で妥当性を確認したHaas-ja-v1.0を使用する．
一般的でない専門用語の認識精度向上のため，カスタム辞書(initial prompt相当)を適用できる．
"""

from __future__ import annotations

import numpy as np

from app.config import ASR_MODEL_ID

_model = None


def _get_model():
    """Haas-jaモデルをロード(初回のみ)して返す関数．

    引数:
        なし
    戻り値:
        model: ロード済みのHaas-jaモデル
    """
    global _model
    if _model is None:
        import haas_asr

        _model = haas_asr.load_model(ASR_MODEL_ID)
    return _model


def transcribe(audio: np.ndarray, domain_terms: dict[str, list[str]] | None = None) -> str:
    """音声波形を文字起こしする関数．

    発話区間の切り出し結果は保存容量を抑えるためAAC(.m4a)で保存しているが，
    AAC形式はlibsndfile(ASRモデルが内部で使用)では読み込めないため，ファイルを
    経由せず，元の音声からデコード済みの波形を直接受け取る．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHzモノラル音声波形(float32, -1.0〜1.0)
        domain_terms (dict[str, list[str]] | None) = None: 専門用語の辞書．
            キーが表記，値が読み(かな)のリスト(例: {"EchoMind": ["エコーマインド"]})
    戻り値:
        text (str): 認識結果のテキスト
    """
    import haas_asr

    model = _get_model()
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    if domain_terms:
        vocabulary = haas_asr.Vocabulary(domain_terms)
        result = model.transcribe([audio], vocabulary=vocabulary)[0]
    else:
        result = model.transcribe([audio])[0]

    return result.text
