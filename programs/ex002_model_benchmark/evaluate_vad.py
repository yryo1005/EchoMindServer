"""VAD(音声区間検出)モデルのベンチマーク評価スクリプト(ex002: 拡充版)．

ex001からの変更点: 比較対象に`pyannote/segmentation-3.0`を追加した．
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

# pyannoteの公式チェックポイントはtorch<2.6時代の形式で保存されているため，
# 信頼済みの提供元として weights_only=Falseを強制する
_original_torch_load = torch.load


def _torch_load_trusted(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


torch.load = _torch_load_trusted

from data import SYNTHETIC_DIR

OUTPUT_DIR = Path("outputs/ex002_model_benchmark/vad")
SAMPLE_RATE = 16000
FRAME_SECONDS = 0.02


def _load_hf_token() -> str:
    """tokens.jsonからHugging Face Hubのトークンを読み込む関数．

    引数:
        なし
    戻り値:
        token (str): Hugging Face Hubのアクセストークン
    """
    with open("tokens.json", encoding="utf-8") as f:
        return json.load(f)["huggingface_hub"]


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
    pcm16 = np.clip(audio * 32768, -32768, 32767).astype(np.int16)
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


def _run_pyannote_segmentation(wav_path: Path, pipeline, n_frames: int) -> np.ndarray:
    """pyannote/segmentation-3.0ベースのVADパイプラインでフレーム単位のラベルを推定する関数．

    引数:
        wav_path (Path): 対象音声ファイルのパス
        pipeline: ロード済みのpyannote VoiceActivityDetectionパイプライン
        n_frames (int): フレーム数
    戻り値:
        labels (np.ndarray): shape=(n_frames,)の0/1配列(1が発話区間)
    """
    labels = np.zeros(n_frames, dtype=np.int32)
    annotation = pipeline(str(wav_path))
    for segment in annotation.get_timeline():
        start_frame = int(segment.start / FRAME_SECONDS)
        end_frame = int(segment.end / FRAME_SECONDS)
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


def evaluate_method(method_name: str, hf_token: str) -> None:
    """指定したVAD手法を全ての疑似会話に対して評価し，結果を保存する関数．

    引数:
        method_name (str): "webrtcvad", "silero_vad", "pyannote_segmentation" のいずれか
        hf_token (str): Hugging Face Hubのアクセストークン(pyannote系で使用)
    戻り値:
        なし
    """
    model = None
    if method_name == "silero_vad":
        from silero_vad import load_silero_vad

        model = load_silero_vad()
    elif method_name == "pyannote_segmentation":
        from pyannote.audio.pipelines import VoiceActivityDetection

        model = VoiceActivityDetection(segmentation="pyannote/segmentation-3.0", use_auth_token=hf_token)
        model.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
        if torch.cuda.is_available():
            model.to(torch.device("cuda"))

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
        elif method_name == "pyannote_segmentation":
            pred_labels = _run_pyannote_segmentation(wav_path, model, n_frames)
        else:
            raise ValueError(f"未知の手法です: {method_name}")

        per_conversation_metrics.append(_precision_recall_f1(pred_labels, gt_labels))

    mean_metrics = {
        key: float(np.mean([m[key] for m in per_conversation_metrics]))
        for key in ["precision", "recall", "f1"]
    }
    std_metrics = {
        key: float(np.std([m[key] for m in per_conversation_metrics]))
        for key in ["precision", "recall", "f1"]
    }

    target_dir = OUTPUT_DIR / method_name
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {"mean": mean_metrics, "std": std_metrics, "per_conversation": per_conversation_metrics},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(method_name, "mean =", mean_metrics, "std =", std_metrics)


if __name__ == "__main__":
    hf_token = _load_hf_token()
    for method_name in ["pyannote_segmentation"]:
        evaluate_method(method_name, hf_token)
