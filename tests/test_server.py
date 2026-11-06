"""EchoMindサーバーの単体テスト．

モデルのロードやDB接続を伴わない，純粋な関数のみを対象とする．
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "programs" / "server"))

from app.pipeline.person_identification import _cosine_similarity  # noqa: E402


def test_cosine_similarity_identical_vectors() -> None:
    """同一ベクトルのコサイン類似度が1.0になることを確認するテスト．"""
    vector = np.array([1.0, 2.0, 3.0])
    assert abs(_cosine_similarity(vector, vector) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors() -> None:
    """直交するベクトルのコサイン類似度が0.0になることを確認するテスト．"""
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert abs(_cosine_similarity(a, b)) < 1e-6


def test_cosine_similarity_opposite_vectors() -> None:
    """正反対のベクトルのコサイン類似度が-1.0になることを確認するテスト．"""
    a = np.array([1.0, 2.0, 3.0])
    b = -a
    assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6
