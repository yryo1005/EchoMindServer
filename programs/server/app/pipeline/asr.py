"""音声認識(ASR)モジュール．

仕様書記載・ベンチマーク(.reports/report_002.md)で妥当性を確認したHaas-ja-v1.0を使用する．
一般的でない専門用語の認識精度向上のため，カスタム辞書(initial prompt相当)を適用できる．
"""

from __future__ import annotations

from pathlib import Path

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


def transcribe(wav_path: Path, domain_terms: dict[str, list[str]] | None = None) -> str:
    """音声ファイルを文字起こしする関数．

    引数:
        wav_path (Path): 対象音声ファイルのパス
        domain_terms (dict[str, list[str]] | None) = None: 専門用語の辞書．
            キーが表記，値が読み(かな)のリスト(例: {"EchoMind": ["エコーマインド"]})
    戻り値:
        text (str): 認識結果のテキスト
    """
    import haas_asr

    model = _get_model()
    audio = haas_asr.load_audio(str(wav_path))

    if domain_terms:
        vocabulary = haas_asr.Vocabulary(domain_terms)
        result = model.transcribe([audio], vocabulary=vocabulary)[0]
    else:
        result = model.transcribe([audio])[0]

    return result.text
