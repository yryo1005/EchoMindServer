"""VAD(音声区間抽出)モジュール．

ベンチマーク(programs/ex002_model_benchmark, .reports/report_002.md)の結果に基づき，
依存ライブラリが軽量で精度も良好なSilero VADを採用する．
"""

from __future__ import annotations

import numpy as np
import torch

from app.config import SAMPLE_RATE

_model = None


def _get_model():
    """Silero VADモデルをロード(初回のみ)して返す関数．

    引数:
        なし
    戻り値:
        model: ロード済みのSilero VADモデル
    """
    global _model
    if _model is None:
        from silero_vad import load_silero_vad

        _model = load_silero_vad()
    return _model


def extract_speech_segments(audio: np.ndarray) -> list[tuple[float, float]]:
    """録音データから発話区間(無音を除いた区間)を抽出する関数．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHzモノラル音声波形(float, -1.0〜1.0)
    戻り値:
        segments (list[tuple[float, float]]): (開始時刻[秒], 終了時刻[秒])のリスト
    """
    from silero_vad import get_speech_timestamps

    model = _get_model()
    wav_tensor = torch.from_numpy(audio).float()
    timestamps = get_speech_timestamps(wav_tensor, model, sampling_rate=SAMPLE_RATE)
    return [(seg["start"] / SAMPLE_RATE, seg["end"] / SAMPLE_RATE) for seg in timestamps]
