"""音声認識(ASR)モデルのベンチマーク評価スクリプト．

JVSコーパスのBASIC5000発話単体(疑似会話に分割する前の単一発話)に対して
各ASRモデルで文字起こしを行い，正解テキストとのCER(文字誤り率)を算出する．
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import jiwer
import numpy as np
import torch
from tqdm import tqdm

from data import _list_speaker_to_files, _load_basic5000_transcripts  # noqa: F401 (再利用)

OUTPUT_DIR = Path("outputs/ex001_model_benchmark/asr")
N_SAMPLES = 200
SEED = 0

CER_TRANSFORM = jiwer.transforms.Compose(
    [
        jiwer.transforms.RemoveMultipleSpaces(),
        jiwer.transforms.Strip(),
        jiwer.transforms.ReduceToListOfListOfChars(),
    ]
)


def _sample_test_set() -> list[tuple[Path, str]]:
    """評価対象となる音声ファイルと正解テキストのペアをサンプリングする関数．

    引数:
        なし
    戻り値:
        samples (list[tuple[Path, str]]): (音声ファイルパス, 正解テキスト)のリスト
    """
    sentence_texts = _load_basic5000_transcripts()
    speaker_to_files = _list_speaker_to_files()

    all_files: list[tuple[Path, str]] = []
    for files in speaker_to_files.values():
        for wav_path, sentence_id in files:
            all_files.append((wav_path, sentence_texts[sentence_id]))

    rng = random.Random(SEED)
    return rng.sample(all_files, k=min(N_SAMPLES, len(all_files)))


def _cer(reference: str, hypothesis: str) -> float:
    """1件のCER(文字誤り率)を計算する関数．

    引数:
        reference (str): 正解テキスト
        hypothesis (str): モデルの認識結果テキスト
    戻り値:
        cer (float): 文字誤り率
    """
    return jiwer.cer(reference, hypothesis, reference_transform=CER_TRANSFORM, hypothesis_transform=CER_TRANSFORM)


def evaluate_haas_ja(samples: list[tuple[Path, str]]) -> None:
    """Haas-ja-v1.0でASR評価を行う関数．

    引数:
        samples (list[tuple[Path, str]]): (音声ファイルパス, 正解テキスト)のリスト
    戻り値:
        なし
    """
    import haas_asr

    model = haas_asr.load_model("third-intelligence/Haas-ja-v1.0")
    records = []
    for wav_path, reference in tqdm(samples, desc="haas_ja", leave=False):
        audio = haas_asr.load_audio(str(wav_path))
        hypothesis = model.transcribe([audio])[0].text
        records.append({"reference": reference, "hypothesis": hypothesis, "cer": _cer(reference, hypothesis)})
    _save_results("haas_ja", records)


def evaluate_transformers_whisper(method_name: str, model_id: str, samples: list[tuple[Path, str]]) -> None:
    """transformersのASRパイプラインを用いて評価を行う関数(kotoba-whisper等)．

    引数:
        method_name (str): 結果保存時に使う手法名
        model_id (str): Hugging Face上のASRモデルのリポジトリID
        samples (list[tuple[Path, str]]): (音声ファイルパス, 正解テキスト)のリスト
    戻り値:
        なし
    """
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    asr_pipeline = pipeline("automatic-speech-recognition", model=model_id, device=device)

    records = []
    for wav_path, reference in tqdm(samples, desc=method_name, leave=False):
        hypothesis = asr_pipeline(str(wav_path))["text"]
        records.append({"reference": reference, "hypothesis": hypothesis, "cer": _cer(reference, hypothesis)})
    _save_results(method_name, records)


def _save_results(method_name: str, records: list[dict]) -> None:
    """評価結果をJSONファイルとして保存する関数．

    引数:
        method_name (str): 結果保存時に使う手法名
        records (list[dict]): 各サンプルのreference/hypothesis/cerを含むリスト
    戻り値:
        なし
    """
    mean_cer = float(np.mean([r["cer"] for r in records]))
    target_dir = OUTPUT_DIR / method_name
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"mean_cer": mean_cer, "records": records}, f, ensure_ascii=False, indent=2)
    print(method_name, "mean CER =", mean_cer)


if __name__ == "__main__":
    test_samples = _sample_test_set()
    evaluate_haas_ja(test_samples)
    evaluate_transformers_whisper("kotoba_whisper_v1_0", "kotoba-tech/kotoba-whisper-v1.0", test_samples)
    evaluate_transformers_whisper("whisper_large_v3", "openai/whisper-large-v3", test_samples)
