"""話者分離モデルのベンチマーク評価スクリプト．

疑似会話音声(data.pyで生成)に対し，pyannote.audioの各話者分離モデルを実行し，
DER(Diarization Error Rate)を算出する．
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

# pyannoteの公式チェックポイントはtorch<2.6時代の形式で保存されているため，
# 信頼済みの提供元として weights_only=Falseを強制する
# (lightning_fabric側がweights_only=Noneを明示的に渡すため，functools.partialでは上書きできない)
# (pyannote.audioをimportする前にtorch.loadをパッチする必要がある)
_original_torch_load = torch.load


def _torch_load_trusted(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


torch.load = _torch_load_trusted

from pyannote.audio import Pipeline  # noqa: E402
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate
from tqdm import tqdm

from data import SYNTHETIC_DIR

OUTPUT_DIR = Path("outputs/ex001_model_benchmark/diarization")


def _load_hf_token() -> str:
    """tokens.jsonからHugging Face Hubのトークンを読み込む関数．

    引数:
        なし
    戻り値:
        token (str): Hugging Face Hubのアクセストークン
    """
    with open("tokens.json", encoding="utf-8") as f:
        return json.load(f)["huggingface_hub"]


def _ground_truth_annotation(metadata: dict) -> Annotation:
    """会話メタデータから正解のpyannote Annotationを作る関数．

    引数:
        metadata (dict): data.pyが生成した会話メタデータ
    戻り値:
        annotation (Annotation): 正解の話者区間アノテーション
    """
    annotation = Annotation()
    for utterance in metadata["utterances"]:
        segment = Segment(utterance["start"], utterance["end"])
        annotation[segment] = utterance["speaker_id"]
    return annotation


def _predicted_annotation(pipeline: Pipeline, wav_path: Path) -> Annotation:
    """pyannoteパイプラインの出力をAnnotationとして取得する関数．

    引数:
        pipeline (Pipeline): ロード済みのpyannote話者分離パイプライン
        wav_path (Path): 対象音声ファイルのパス
    戻り値:
        annotation (Annotation): 推定された話者区間アノテーション
    """
    diarization = pipeline(str(wav_path))
    annotation = Annotation()
    for segment, _, speaker_label in diarization.itertracks(yield_label=True):
        annotation[segment] = speaker_label
    return annotation


def evaluate_method(method_name: str, repo_id: str, hf_token: str) -> None:
    """指定した話者分離モデルを全ての疑似会話に対して評価し，結果を保存する関数．

    引数:
        method_name (str): 結果保存時に使う手法名
        repo_id (str): Hugging Face上のpyannoteパイプラインのリポジトリID
        hf_token (str): Hugging Face Hubのアクセストークン
    戻り値:
        なし
    """
    pipeline = Pipeline.from_pretrained(repo_id, use_auth_token=hf_token)
    if pipeline is None:
        raise RuntimeError(f"パイプラインのロードに失敗しました: {repo_id}")

    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    metric = DiarizationErrorRate()
    metadata_paths = sorted(SYNTHETIC_DIR.glob("conv_*.json"))
    per_conversation_der = []
    for metadata_path in tqdm(metadata_paths, desc=method_name, leave=False):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        wav_path = metadata_path.with_suffix(".wav")

        reference = _ground_truth_annotation(metadata)
        hypothesis = _predicted_annotation(pipeline, wav_path)

        der = metric(reference, hypothesis)
        per_conversation_der.append(float(der))

    mean_der = float(np.mean(per_conversation_der))

    target_dir = OUTPUT_DIR / method_name
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {"mean_der": mean_der, "per_conversation_der": per_conversation_der},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(method_name, "mean DER =", mean_der)


if __name__ == "__main__":
    # pyannote/speaker-diarization-community-1は，本環境のpyannote.audio==3.3.2では
    # SpeakerDiarizationパイプラインの初期化引数(plda)が非互換のため評価対象から除外する．
    # (community-1には他の多数の依存ライブラリをメジャーバージョンアップする必要があり，
    #  Haas-ja等が依存する環境を壊すリスクがあるため，別環境での追加検証が必要)
    hf_token = _load_hf_token()
    for method_name, repo_id in [
        ("pyannote_3.1", "pyannote/speaker-diarization-3.1"),
    ]:
        evaluate_method(method_name, repo_id, hf_token)
