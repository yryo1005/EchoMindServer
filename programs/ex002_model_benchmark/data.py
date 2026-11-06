"""JVSコーパスから疑似複数話者会話データを構築するモジュール(ex002: 拡充版)．

ex001からの変更点:
    - 会話数・話者数・発話数を増やし，より多様なデータとする．
    - 発話間に無音を挟むだけでなく，一定確率で発話を重複(オーバーラップ)させる．
    - 加算的white noiseを混入させ，よりノイズの多い実環境に近い条件を再現する．
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

RAW_DIR = Path("datasets/ex001_model_benchmark/raw")  # JVS生データはex001のものを再利用する
JVS_WAV_DIR = RAW_DIR / "jvs"
BASIC5000_YAML = RAW_DIR / "transcripts" / "basic5000.yaml"
SYNTHETIC_DIR = Path("datasets/ex002_model_benchmark/synthetic")
SAMPLE_RATE = 16000


@dataclass
class Utterance:
    """1つの発話区間の正解ラベル．

    属性:
        start (float): 会話音声内での発話開始時刻[秒]
        end (float): 会話音声内での発話終了時刻[秒]
        speaker_id (str): 話者ID(JVSの話者ラベル, 例: "jvs001")
        text (str): 発話内容の正解テキスト
    """

    start: float
    end: float
    speaker_id: str
    text: str


def _load_basic5000_transcripts() -> dict[str, str]:
    """BASIC5000文章セットの正解テキストを読み込む関数．

    引数:
        なし
    戻り値:
        sentence_id_to_text (dict[str, str]): 文章ID("BASIC5000_0001"等)から正解テキストへの辞書
    """
    with open(BASIC5000_YAML, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {sentence_id: entry["text_level1"] for sentence_id, entry in raw.items()}


def _list_speaker_to_files() -> dict[str, list[tuple[Path, str]]]:
    """話者ごとに利用可能な(音声ファイルパス, 文章ID)の一覧を作る関数．

    引数:
        なし
    戻り値:
        speaker_to_files (dict[str, list[tuple[Path, str]]]): 話者IDから(ファイルパス, 文章ID)一覧への辞書
    """
    speaker_to_files: dict[str, list[tuple[Path, str]]] = {}
    for wav_path in sorted(JVS_WAV_DIR.glob("*_nonpara30_*_BASIC5000_*.wav")):
        name = wav_path.stem
        parts = name.split("_")
        speaker_id = parts[2]
        sentence_id = "_".join(parts[-2:])
        speaker_to_files.setdefault(speaker_id, []).append((wav_path, sentence_id))
    return speaker_to_files


def _add_white_noise(audio: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """指定したSNRとなるよう加算的white noiseを混入させる関数．

    引数:
        audio (np.ndarray): shape=(n_samples,)の原音声波形
        snr_db (float): 目標のSNR[dB]
        rng (np.random.Generator): 乱数生成器
    戻り値:
        noisy_audio (np.ndarray): shape=(n_samples,)のノイズ混入後の波形
    """
    signal_power = float(np.mean(audio ** 2)) + 1e-12
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = rng.normal(0.0, np.sqrt(noise_power), size=audio.shape)
    return audio + noise


def build_synthetic_conversations(
    n_conversations: int = 80,
    n_speakers_range: tuple[int, int] = (2, 4),
    n_utterances_per_speaker_range: tuple[int, int] = (3, 6),
    silence_seconds_range: tuple[float, float] = (0.4, 1.2),
    overlap_probability: float = 0.3,
    overlap_seconds_range: tuple[float, float] = (0.3, 1.5),
    snr_db_range: tuple[float, float] = (10.0, 25.0),
    seed: int = 0,
) -> list[Path]:
    """疑似複数話者会話を複数件生成し，音声とラベルをDiskに保存する関数．

    JVSコーパスの単一話者発話をランダムに選び，無音または重複を挟んで結合し，
    加算的white noiseを混入させることで，実環境に近い疑似会話音声を作成する．

    引数:
        n_conversations (int) = 80: 生成する会話の件数
        n_speakers_range (tuple[int, int]) = (2, 4): 1会話あたりの話者数の範囲(両端含む)
        n_utterances_per_speaker_range (tuple[int, int]) = (3, 6): 話者ごとの発話数の範囲(両端含む)
        silence_seconds_range (tuple[float, float]) = (0.4, 1.2): 発話間の無音長の範囲[秒](重複しない場合)
        overlap_probability (float) = 0.3: 発話間を重複させる確率
        overlap_seconds_range (tuple[float, float]) = (0.3, 1.5): 重複させる場合の重複長の範囲[秒]
        snr_db_range (tuple[float, float]) = (10.0, 25.0): 混入させるwhite noiseのSNR範囲[dB]
        seed (int) = 0: 乱数シード
    戻り値:
        metadata_paths (list[Path]): 生成した各会話のメタデータ(json)ファイルパスの一覧
    """
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

    sentence_texts = _load_basic5000_transcripts()
    speaker_to_files = _list_speaker_to_files()
    speaker_ids = list(speaker_to_files.keys())

    metadata_paths: list[Path] = []
    for conv_idx in range(n_conversations):
        n_speakers = rng.randint(*n_speakers_range)
        conv_speakers = rng.sample(speaker_ids, k=n_speakers)

        pending_utterances: list[tuple[str, Path, str]] = []
        for speaker_id in conv_speakers:
            n_utt = rng.randint(*n_utterances_per_speaker_range)
            available = speaker_to_files[speaker_id]
            chosen = rng.sample(available, k=min(n_utt, len(available)))
            for wav_path, sentence_id in chosen:
                pending_utterances.append((speaker_id, wav_path, sentence_id))
        rng.shuffle(pending_utterances)

        # 各発話を読み込み，開始時刻を決める(全体の長さが確定してからノイズを混入するため，
        # 一旦は波形バッファに直接加算していく)
        total_duration = 0.0
        loaded = []
        for speaker_id, wav_path, sentence_id in pending_utterances:
            audio, sr = sf.read(wav_path)
            if sr != SAMPLE_RATE:
                raise ValueError(f"想定外のサンプリングレートです: {wav_path} ({sr}Hz)")
            loaded.append((speaker_id, audio, sentence_texts[sentence_id]))
            total_duration += len(audio) / sr

        # 発話間のギャップ(無音または重複)を見積もって会話全体の長さを確保する
        gaps = []
        for _ in range(len(loaded) - 1):
            if rng.random() < overlap_probability:
                gaps.append(-rng.uniform(*overlap_seconds_range))
            else:
                gaps.append(rng.uniform(*silence_seconds_range))
        total_duration += sum(max(g, 0.0) for g in gaps)
        buffer_length = int((total_duration + 2.0) * SAMPLE_RATE)
        conversation_buffer = np.zeros(buffer_length)

        utterances: list[Utterance] = []
        cursor = 0.0
        for i, (speaker_id, audio, text) in enumerate(loaded):
            duration = len(audio) / SAMPLE_RATE
            start_sample = int(cursor * SAMPLE_RATE)
            conversation_buffer[start_sample:start_sample + len(audio)] += audio
            utterances.append(Utterance(start=cursor, end=cursor + duration, speaker_id=speaker_id, text=text))

            if i < len(gaps):
                cursor = cursor + duration + gaps[i]
                cursor = max(cursor, 0.0)
            else:
                cursor = cursor + duration

        end_sample = int(max(u.end for u in utterances) * SAMPLE_RATE) + SAMPLE_RATE
        conversation_audio = conversation_buffer[:end_sample]

        snr_db = rng.uniform(*snr_db_range)
        conversation_audio = _add_white_noise(conversation_audio, snr_db, np_rng)

        conv_name = f"conv_{conv_idx:03d}"
        sf.write(SYNTHETIC_DIR / f"{conv_name}.wav", conversation_audio, SAMPLE_RATE)

        metadata_path = SYNTHETIC_DIR / f"{conv_name}.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "conversation_id": conv_name,
                    "speakers": conv_speakers,
                    "snr_db": snr_db,
                    "utterances": [asdict(u) for u in sorted(utterances, key=lambda u: u.start)],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        metadata_paths.append(metadata_path)

    return metadata_paths


if __name__ == "__main__":
    paths = build_synthetic_conversations()
    print(f"{len(paths)}件の疑似会話を {SYNTHETIC_DIR} に生成しました．")
