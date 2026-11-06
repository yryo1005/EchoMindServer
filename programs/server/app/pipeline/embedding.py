"""文章埋め込み(ベクトル化)モジュール．

仕様書記載・ベンチマーク(.reports/report_002.md)で妥当性を確認したruri-large-v2を使用する．
"""

from __future__ import annotations

import numpy as np

from app.config import EMBEDDING_MODEL_ID

_model = None


def _get_model():
    """ruri-large-v2モデルをロード(初回のみ)して返す関数．

    引数:
        なし
    戻り値:
        model: ロード済みのSentenceTransformerモデル
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_ID)
    return _model


def embed_passage(text: str) -> np.ndarray:
    """検索対象となる文章(発言テキスト)をベクトル化する関数．

    引数:
        text (str): ベクトル化する発言テキスト
    戻り値:
        embedding (np.ndarray): shape=(1024,)の文章ベクトル
    """
    model = _get_model()
    return model.encode([f"文章: {text}"], normalize_embeddings=True)[0]


def embed_query(text: str) -> np.ndarray:
    """検索クエリ(質問文)をベクトル化する関数．

    引数:
        text (str): ベクトル化する質問文
    戻り値:
        embedding (np.ndarray): shape=(1024,)の質問文ベクトル
    """
    model = _get_model()
    return model.encode([f"クエリ: {text}"], normalize_embeddings=True)[0]
