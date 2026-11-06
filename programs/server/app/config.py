"""EchoMindサーバーの設定値をまとめるモジュール．"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVER_ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = SERVER_ROOT / "storage"
UPLOADED_AUDIO_DIR = STORAGE_DIR / "uploaded"
UTTERANCE_AUDIO_DIR = STORAGE_DIR / "utterances"

DATABASE_URL = "postgresql+psycopg2://echomind:echomind@localhost:5432/echomind"

# 仕様書で定められたモデル選定
# (programs/ex001_model_benchmark, programs/ex002_model_benchmark のベンチマーク結果に基づく. .reports/report_002.md 参照)
VAD_MODEL_NAME = "silero_vad"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-3.1"
SPEAKER_EMBEDDING_MODEL_ID = "pyannote/embedding"
ASR_MODEL_ID = "third-intelligence/Haas-ja-v1.0"
EMBEDDING_MODEL_ID = "cl-nagoya/ruri-large-v2"
EMBEDDING_DIM = 1024

# 話者ID統合のためのコサイン類似度の閾値(これ以上なら同一人物と判定する)
SPEAKER_MATCH_THRESHOLD = 0.7

# 名前推定を試みる最低発話数(これ未満の人物IDは名前推定の対象としない)
NAME_ESTIMATION_MIN_UTTERANCE_COUNT = 10

SAMPLE_RATE = 16000


def load_tokens() -> dict:
    """プロジェクトルートのtokens.jsonを読み込む関数．

    引数:
        なし
    戻り値:
        tokens (dict): "huggingface_hub", "gemini" 等のAPIキーを含む辞書
    """
    tokens_path = PROJECT_ROOT / "tokens.json"
    with open(tokens_path, encoding="utf-8") as f:
        return json.load(f)
