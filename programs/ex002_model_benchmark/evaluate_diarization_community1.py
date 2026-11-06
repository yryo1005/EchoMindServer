"""話者分離モデルのベンチマーク評価スクリプト(ex002: community-1専用)．

`pyannote/speaker-diarization-community-1`は，評価に`pyannote.audio>=4.0`が必要であり，
`evaluate_diarization.py`が使用する`.venv_ml`(pyannote.audio==3.3.2, Haas-ja等が依存)とは
ライブラリバージョンが競合するため，別の仮想環境`.venv_diarization_community`で実行する．

実行方法:
    .venv_diarization_community/bin/python programs/ex002_model_benchmark/evaluate_diarization_community1.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

_original_torch_load = torch.load


def _torch_load_trusted(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)


torch.load = _torch_load_trusted

from pyannote.audio import Pipeline  # noqa: E402
from pyannote.core import Annotation, Segment  # noqa: E402
from pyannote.metrics.diarization import DiarizationErrorRate  # noqa: E402
from tqdm import tqdm  # noqa: E402

SYNTHETIC_DIR = Path("datasets/ex002_model_benchmark/synthetic")
OUTPUT_DIR = Path("outputs/ex002_model_benchmark/diarization")


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
    output = pipeline(str(wav_path))
    diarization = output.speaker_diarization if hasattr(output, "speaker_diarization") else output
    annotation = Annotation()
    for segment, _, speaker_label in diarization.itertracks(yield_label=True):
        annotation[segment] = speaker_label
    return annotation


def main() -> None:
    """community-1を全ての疑似会話に対して評価し，結果を保存する関数．

    引数:
        なし
    戻り値:
        なし
    """
    hf_token = _load_hf_token()
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=hf_token)
    if pipeline is None:
        raise RuntimeError("パイプラインのロードに失敗しました: pyannote/speaker-diarization-community-1")

    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))

    metric = DiarizationErrorRate()
    metadata_paths = sorted(SYNTHETIC_DIR.glob("conv_*.json"))
    per_conversation_der = []
    for metadata_path in tqdm(metadata_paths, desc="pyannote_community_1", leave=False):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        wav_path = metadata_path.with_suffix(".wav")

        reference = _ground_truth_annotation(metadata)
        hypothesis = _predicted_annotation(pipeline, wav_path)

        der = metric(reference, hypothesis)
        per_conversation_der.append(float(der))

    mean_der = float(np.mean(per_conversation_der))
    std_der = float(np.std(per_conversation_der))

    target_dir = OUTPUT_DIR / "pyannote_community_1"
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(
            {"mean_der": mean_der, "std_der": std_der, "per_conversation_der": per_conversation_der},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print("pyannote_community_1", "mean DER =", mean_der, "std DER =", std_der)


if __name__ == "__main__":
    main()
