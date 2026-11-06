"""JVSコーパスから疑似複数話者会話データを構築するモジュール．

VAD・話者分離・音声認識・ベクトル検索の各ベンチマークで共通して使用する
疑似会話データ（音声・話者区間・発話テキストの正解ラベル付き）を生成する．
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

RAW_DIR = Path("datasets/ex001_model_benchmark/raw")
JVS_WAV_DIR = RAW_DIR / "jvs"
BASIC5000_YAML = RAW_DIR / "transcripts" / "basic5000.yaml"
SYNTHETIC_DIR = Path("datasets/ex001_model_benchmark/synthetic")
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

    nonpara30セットのうちBASIC5000に属する発話のみを対象とする
    (話者ごとに異なる文章が収録されており，疑似会話の多様性を確保しやすいため)．

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


def build_synthetic_conversations(
    n_conversations: int = 30,
    n_speakers_range: tuple[int, int] = (2, 3),
    n_utterances_per_speaker_range: tuple[int, int] = (3, 5),
    silence_seconds_range: tuple[float, float] = (0.4, 1.2),
    seed: int = 0,
) -> list[Path]:
    """疑似複数話者会話を複数件生成し，音声とラベルをDiskに保存する関数．

    JVSコーパスの単一話者発話をランダムに選び，無音区間を挟んで結合することで，
    発話区間・話者・テキストの正解ラベルが既知の疑似会話音声を作成する．

    引数:
        n_conversations (int) = 30: 生成する会話の件数
        n_speakers_range (tuple[int, int]) = (2, 3): 1会話あたりの話者数の範囲(両端含む)
        n_utterances_per_speaker_range (tuple[int, int]) = (3, 5): 話者ごとの発話数の範囲(両端含む)
        silence_seconds_range (tuple[float, float]) = (0.4, 1.2): 発話間の無音長の範囲[秒]
        seed (int) = 0: 乱数シード
    戻り値:
        metadata_paths (list[Path]): 生成した各会話のメタデータ(json)ファイルパスの一覧
    """
    rng = random.Random(seed)
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

    sentence_texts = _load_basic5000_transcripts()
    speaker_to_files = _list_speaker_to_files()
    speaker_ids = list(speaker_to_files.keys())

    metadata_paths: list[Path] = []
    for conv_idx in range(n_conversations):
        n_speakers = rng.randint(*n_speakers_range)
        conv_speakers = rng.sample(speaker_ids, k=n_speakers)

        # 各話者の発話をプールから選び、話者ラベル付きの発話リストを作る
        pending_utterances: list[tuple[str, Path, str]] = []
        for speaker_id in conv_speakers:
            n_utt = rng.randint(*n_utterances_per_speaker_range)
            available = speaker_to_files[speaker_id]
            chosen = rng.sample(available, k=min(n_utt, len(available)))
            for wav_path, sentence_id in chosen:
                pending_utterances.append((speaker_id, wav_path, sentence_id))
        rng.shuffle(pending_utterances)

        audio_segments: list[np.ndarray] = []
        utterances: list[Utterance] = []
        cursor = 0.0
        for speaker_id, wav_path, sentence_id in pending_utterances:
            audio, sr = sf.read(wav_path)
            if sr != SAMPLE_RATE:
                raise ValueError(f"想定外のサンプリングレートです: {wav_path} ({sr}Hz)")
            duration = len(audio) / sr
            utterances.append(
                Utterance(
                    start=cursor,
                    end=cursor + duration,
                    speaker_id=speaker_id,
                    text=sentence_texts[sentence_id],
                )
            )
            audio_segments.append(audio)
            cursor += duration

            silence_seconds = rng.uniform(*silence_seconds_range)
            audio_segments.append(np.zeros(int(silence_seconds * SAMPLE_RATE)))
            cursor += silence_seconds

        conversation_audio = np.concatenate(audio_segments)
        conv_name = f"conv_{conv_idx:03d}"
        sf.write(SYNTHETIC_DIR / f"{conv_name}.wav", conversation_audio, SAMPLE_RATE)

        metadata_path = SYNTHETIC_DIR / f"{conv_name}.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "conversation_id": conv_name,
                    "speakers": conv_speakers,
                    "utterances": [asdict(u) for u in utterances],
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
