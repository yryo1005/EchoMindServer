"""話者分離結果に基づき，発言(発声)ごとに音声を切り出すモジュール．

切り出した音声は，保存容量を抑えるため非圧縮のwavではなく軽量なAAC(.m4a)形式で保存する．
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydub import AudioSegment

from app.config import SAMPLE_RATE
from app.pipeline.diarization import SpeakerSegment

CLIP_EXTENSION = ".m4a"


def _write_as_aac(clip_audio: np.ndarray, clip_path: Path) -> None:
    """float配列の音声波形をAAC(.m4a)形式でファイルに書き出す関数．

    引数:
        clip_audio (np.ndarray): shape=(n_samples,)の16kHzモノラル音声波形(float, -1.0〜1.0)
        clip_path (Path): 書き出し先のファイルパス(拡張子は.m4a)
    戻り値:
        なし
    """
    pcm16 = np.clip(clip_audio * 32767, -32768, 32767).astype(np.int16)
    audio_segment = AudioSegment(
        data=pcm16.tobytes(),
        sample_width=2,
        frame_rate=SAMPLE_RATE,
        channels=1,
    )
    audio_segment.export(clip_path, format="ipod", codec="aac")


def cut_utterance_clips(
    audio: np.ndarray, segments: list[SpeakerSegment], output_dir: Path
) -> list[tuple[Path, np.ndarray]]:
    """話者区間ごとに音声を切り出し，個別のAAC(.m4a)ファイルとして保存する関数．

    AAC形式はASRモデルが内部で使うlibsndfileで読み込めないため，保存したファイルパスに加え，
    ASRでそのまま使える切り出し済みの波形(デコード前の無劣化なデータ)も合わせて返す．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHzモノラル音声波形
        segments (list[SpeakerSegment]): 話者分離で得られた話者区間のリスト
        output_dir (Path): 切り出した音声ファイルの保存先ディレクトリ
    戻り値:
        clips (list[tuple[Path, np.ndarray]]): segmentsと同じ順序の，
            (保存した音声ファイルパス, 切り出した波形)のリスト
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, segment in enumerate(segments):
        start_sample = int(segment.start * SAMPLE_RATE)
        end_sample = int(segment.end * SAMPLE_RATE)
        clip_audio = audio[start_sample:end_sample]

        clip_path = output_dir / f"utterance_{i:04d}{CLIP_EXTENSION}"
        _write_as_aac(clip_audio, clip_path)
        clips.append((clip_path, clip_audio))
    return clips
