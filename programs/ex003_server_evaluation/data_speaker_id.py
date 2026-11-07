"""話者ID統合の精度検証用データを生成するモジュール．

JVSコーパスの話者プールから，同一話者が複数の別々の「会話」(アップロード)に
跨って登場するような疑似データを作成する．各会話は`programs/ex002_model_benchmark/data.py`
と同様に重複発話・ノイズを含む，より実環境に近い条件で生成する．
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

RAW_DIR = Path("datasets/ex001_model_benchmark/raw")
JVS_WAV_DIR = RAW_DIR / "jvs"
OUTPUT_DIR = Path("datasets/ex003_server_evaluation/speaker_id_sessions")
SAMPLE_RATE = 16000

N_SESSIONS = 15
SPEAKER_POOL_SIZE = 10
N_SPEAKERS_PER_SESSION_RANGE = (2, 3)
N_UTTERANCES_PER_SPEAKER_RANGE = (3, 5)
SNR_DB_RANGE = (10.0, 25.0)


@dataclass
class GroundTruthUtterance:
    """正解ラベル付きの発話区間．

    属性:
        start (float): 会話音声内での発話開始時刻[秒]
        end (float): 会話音声内での発話終了時刻[秒]
        true_speaker_id (str): 正解の話者ID(JVSラベル, 例: "jvs001")
    """

    start: float
    end: float
    true_speaker_id: str


def _list_speaker_to_files() -> dict[str, list[tuple[Path, str]]]:
    """話者ごとに利用可能な(音声ファイルパス, 文章ID)の一覧を作る関数．"""
    speaker_to_files: dict[str, list[tuple[Path, str]]] = {}
    for wav_path in sorted(JVS_WAV_DIR.glob("*_nonpara30_*_BASIC5000_*.wav")):
        name = wav_path.stem
        parts = name.split("_")
        speaker_id = parts[2]
        sentence_id = "_".join(parts[-2:])
        speaker_to_files.setdefault(speaker_id, []).append((wav_path, sentence_id))
    return speaker_to_files


def _add_white_noise(audio: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """指定したSNRとなるよう加算的white noiseを混入させる関数．"""
    signal_power = float(np.mean(audio ** 2)) + 1e-12
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = rng.normal(0.0, np.sqrt(noise_power), size=audio.shape)
    return audio + noise


def build_multi_session_data(seed: int = 0) -> list[Path]:
    """複数の別々の会話(セッション)に跨って同一話者が登場する疑似データを生成する関数．

    話者プール(`SPEAKER_POOL_SIZE`人)からランダムに話者を選んで各セッションを構成するため，
    セッション数がプールサイズより多い場合，同一話者が複数セッションに登場することになる．

    引数:
        seed (int) = 0: 乱数シード
    戻り値:
        metadata_paths (list[Path]): 生成した各セッションのメタデータ(json)ファイルパスの一覧
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    speaker_to_files = _list_speaker_to_files()
    speaker_pool = rng.sample(list(speaker_to_files.keys()), k=SPEAKER_POOL_SIZE)

    metadata_paths = []
    for session_idx in range(N_SESSIONS):
        n_speakers = rng.randint(*N_SPEAKERS_PER_SESSION_RANGE)
        session_speakers = rng.sample(speaker_pool, k=n_speakers)

        pending = []
        for speaker_id in session_speakers:
            n_utt = rng.randint(*N_UTTERANCES_PER_SPEAKER_RANGE)
            available = speaker_to_files[speaker_id]
            chosen = rng.sample(available, k=min(n_utt, len(available)))
            for wav_path, sentence_id in chosen:
                pending.append((speaker_id, wav_path, sentence_id))
        rng.shuffle(pending)

        audio_segments = []
        utterances = []
        cursor = 0.0
        for speaker_id, wav_path, sentence_id in pending:
            audio, sr = sf.read(wav_path)
            assert sr == SAMPLE_RATE
            duration = len(audio) / sr
            utterances.append(GroundTruthUtterance(start=cursor, end=cursor + duration, true_speaker_id=speaker_id))
            audio_segments.append(audio)
            cursor += duration

            silence = rng.uniform(0.4, 1.2)
            audio_segments.append(np.zeros(int(silence * SAMPLE_RATE)))
            cursor += silence

        session_audio = np.concatenate(audio_segments)
        snr_db = rng.uniform(*SNR_DB_RANGE)
        session_audio = _add_white_noise(session_audio, snr_db, np_rng)

        session_name = f"session_{session_idx:03d}"
        sf.write(OUTPUT_DIR / f"{session_name}.wav", session_audio, SAMPLE_RATE)

        metadata_path = OUTPUT_DIR / f"{session_name}.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": session_name,
                    "true_speakers": session_speakers,
                    "utterances": [asdict(u) for u in utterances],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        metadata_paths.append(metadata_path)

    return metadata_paths


if __name__ == "__main__":
    paths = build_multi_session_data()
    print(f"{len(paths)}件のセッションを {OUTPUT_DIR} に生成しました．")
