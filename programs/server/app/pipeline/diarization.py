"""話者分離モジュール．

ベンチマーク(.reports/report_002.md)の結果に基づき，仕様書記載の
`pyannote/speaker-diarization-3.1`を採用する．話者分離と同時に，話者ID統合に用いる
256次元の話者埋め込み(`return_embeddings=True`)も取得する．
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from app.config import DIARIZATION_MODEL_ID, load_tokens

# pyannoteの公式チェックポイントはtorch<2.6時代の形式で保存されているため，
# 信頼済みの提供元として weights_only=Falseを強制する
_original_torch_load = torch.load


def _torch_load_trusted(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


torch.load = _torch_load_trusted

from pyannote.audio import Pipeline  # noqa: E402

_pipeline: Pipeline | None = None


@dataclass
class SpeakerSegment:
    """1つの話者区間を表すデータクラス．

    属性:
        start (float): 区間の開始時刻[秒]
        end (float): 区間の終了時刻[秒]
        temp_speaker_label (str): 会話内で一時的に割り当てられた話者ラベル(例: "SPEAKER_00")
    """

    start: float
    end: float
    temp_speaker_label: str


def _get_pipeline() -> Pipeline:
    """話者分離パイプラインをロード(初回のみ)して返す関数．

    引数:
        なし
    戻り値:
        pipeline (Pipeline): ロード済みのpyannote話者分離パイプライン
    """
    global _pipeline
    if _pipeline is None:
        hf_token = load_tokens()["huggingface_hub"]
        _pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL_ID, use_auth_token=hf_token)
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
    return _pipeline


def diarize(wav_path: Path) -> tuple[list[SpeakerSegment], dict[str, np.ndarray]]:
    """音声ファイルに対して話者分離を行う関数．

    引数:
        wav_path (Path): 対象音声ファイルのパス
    戻り値:
        segments (list[SpeakerSegment]): 話者区間のリスト(時系列順)
        speaker_embeddings (dict[str, np.ndarray]): 一時話者ラベルから256次元埋め込みへの辞書
    """
    pipeline = _get_pipeline()
    annotation, embeddings = pipeline(str(wav_path), return_embeddings=True)

    segments = [
        SpeakerSegment(start=segment.start, end=segment.end, temp_speaker_label=speaker_label)
        for segment, _, speaker_label in annotation.itertracks(yield_label=True)
    ]
    segments.sort(key=lambda s: s.start)

    labels = annotation.labels()
    speaker_embeddings = {label: embeddings[i] for i, label in enumerate(labels)}

    return segments, speaker_embeddings
