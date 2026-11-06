"""VAD(音声区間検出)モデルのベンチマーク評価スクリプト．

疑似会話音声(data.pyで生成)の正解発話区間と，各VAD手法が検出した区間を比較し，
フレーム単位のPrecision/Recall/F1を算出する．
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import webrtcvad
from tqdm import tqdm

from data import SYNTHETIC_DIR

OUTPUT_DIR = Path("outputs/ex001_model_benchmark/vad")
SAMPLE_RATE = 16000
FRAME_SECONDS = 0.02


def _ground_truth_frame_labels(metadata: dict, n_frames: int) -> np.ndarray:
    """正解の発話区間からフレーム単位の音声/無音ラベルを作る関数．

    引数:
        metadata (dict): data.pyが生成した会話メタデータ
        n_frames (int): フレーム数
    戻り値:
        labels (np.ndarray): shape=(n_frames,)の0/1配列(1が発話区間)
    """
    labels = np.zeros(n_frames, dtype=np.int32)
    for utterance in metadata["utterances"]:
        start_frame = int(utterance["start"] / FRAME_SECONDS)
        end_frame = int(utterance["end"] / FRAME_SECONDS)
        labels[start_frame:min(end_frame, n_frames)] = 1
    return labels


def _run_webrtcvad(audio: np.ndarray, aggressiveness: int = 2) -> np.ndarray:
    """WebRTC VADでフレーム単位の音声/無音ラベルを推定する関数．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHz音声波形(float)
        aggressiveness (int) = 2: WebRTC VADの感度(0〜3)
    戻り値:
        labels (np.ndarray): shape=(n_frames,)の0/1配列(1が発話区間)
    """
    vad = webrtcvad.Vad(aggressiveness)
    pcm16 = (audio * 32768).astype(np.int16)
    frame_len = int(SAMPLE_RATE * FRAME_SECONDS)
    n_frames = len(pcm16) // frame_len
    labels = np.zeros(n_frames, dtype=np.int32)
    for i in range(n_frames):
        frame = pcm16[i * frame_len:(i + 1) * frame_len].tobytes()
        labels[i] = int(vad.is_speech(frame, SAMPLE_RATE))
    return labels


def _run_silero_vad(audio: np.ndarray, model) -> np.ndarray:
    """Silero VADでフレーム単位の音声/無音ラベルを推定する関数．

    引数:
        audio (np.ndarray): shape=(n_samples,)の16kHz音声波形(float)
        model: ロード済みのSilero VADモデル
    戻り値:
        labels (np.ndarray): shape=(n_frames,)の0/1配列(1が発話区間)
    """
    from silero_vad import get_speech_timestamps

    n_frames = len(audio) // int(SAMPLE_RATE * FRAME_SECONDS)
    labels = np.zeros(n_frames, dtype=np.int32)
    wav_tensor = torch.from_numpy(audio).float()
    timestamps = get_speech_timestamps(wav_tensor, model, sampling_rate=SAMPLE_RATE)
    for seg in timestamps:
        start_frame = int(seg["start"] / SAMPLE_RATE / FRAME_SECONDS)
        end_frame = int(seg["end"] / SAMPLE_RATE / FRAME_SECONDS)
        labels[start_frame:min(end_frame, n_frames)] = 1
    return labels


def _precision_recall_f1(pred: np.ndarray, gt: np.ndarray) -> dict[str, float]:
    """フレーム単位のPrecision/Recall/F1を計算する関数．

    引数:
        pred (np.ndarray): 予測ラベル(0/1)
        gt (np.ndarray): 正解ラベル(0/1)
    戻り値:
        metrics (dict[str, float]): precision, recall, f1を含む辞書
    """
    n = min(len(pred), len(gt))
    pred, gt = pred[:n], gt[:n]
    tp = int(((pred == 1) & (gt == 1)).sum())
    fp = int(((pred == 1) & (gt == 0)).sum())
    fn = int(((pred == 0) & (gt == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate_method(method_name: str) -> None:
    """指定したVAD手法を全ての疑似会話に対して評価し，結果を保存する関数．

    引数:
        method_name (str): "webrtcvad" または "silero_vad"
    戻り値:
        なし
    """
    if method_name == "silero_vad":
        from silero_vad import load_silero_vad

        model = load_silero_vad()

    metadata_paths = sorted(SYNTHETIC_DIR.glob("conv_*.json"))
    per_conversation_metrics = []
    for metadata_path in tqdm(metadata_paths, desc=method_name, leave=False):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        wav_path = metadata_path.with_suffix(".wav")
        audio, sr = sf.read(wav_path)
        assert sr == SAMPLE_RATE

        n_frames = len(audio) // int(SAMPLE_RATE * FRAME_SECONDS)
        gt_labels = _ground_truth_frame_labels(metadata, n_frames)

        if method_name == "webrtcvad":
            pred_labels = _run_webrtcvad(audio)
        elif method_name == "silero_vad":
            pred_labels = _run_silero_vad(audio, model)
        else:
            raise ValueError(f"未知の手法です: {method_name}")

        per_conversation_metrics.append(_precision_recall_f1(pred_labels, gt_labels))

    mean_metrics = {
        key: float(np.mean([m[key] for m in per_conversation_metrics]))
        for key in ["precision", "recall", "f1"]
    }

    target_dir = OUTPUT_DIR / method_name
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {"mean": mean_metrics, "per_conversation": per_conversation_metrics},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(method_name, mean_metrics)


if __name__ == "__main__":
    for method_name in ["webrtcvad", "silero_vad"]:
        evaluate_method(method_name)
