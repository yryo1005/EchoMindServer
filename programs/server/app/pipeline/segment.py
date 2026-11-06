"""話者分離結果に基づき，発言(発声)ごとに音声を切り出すモジュール．"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import SAMPLE_RATE
from app.pipeline.diarization import SpeakerSegment


def cut_utterance_clips(audio: np.ndarray, segments: list[SpeakerSegment], output_dir: Path) -> list[Path]:
    """話者区間ごとに音声を切り出し，個別のwavファイルとして保存する関数．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHzモノラル音声波形
        segments (list[SpeakerSegment]): 話者分離で得られた話者区間のリスト
        output_dir (Path): 切り出した音声ファイルの保存先ディレクトリ
    戻り値:
        clip_paths (list[Path]): segmentsと同じ順序の，切り出した音声ファイルパスのリスト
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []
    for i, segment in enumerate(segments):
        start_sample = int(segment.start * SAMPLE_RATE)
        end_sample = int(segment.end * SAMPLE_RATE)
        clip_audio = audio[start_sample:end_sample]

        clip_path = output_dir / f"utterance_{i:04d}.wav"
        sf.write(clip_path, clip_audio, SAMPLE_RATE)
        clip_paths.append(clip_path)
    return clip_paths
