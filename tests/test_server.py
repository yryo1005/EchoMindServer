"""EchoMindサーバーの単体テスト．

モデルのロードやDB接続を伴わない，純粋な関数のみを対象とする．
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "programs" / "server"))

from app.api.browse import ConversationSummaryOut, UpdatePersonNameIn  # noqa: E402
from app.pipeline.person_identification import _cosine_similarity  # noqa: E402
from app.services.gemini_client import _is_daily_quota_exceeded  # noqa: E402


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


def test_is_daily_quota_exceeded_detects_per_day_limit() -> None:
    """1日あたりのリクエスト数上限のエラーを正しく検出できることを確認するテスト．"""
    error = Exception(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generate_content_free_tier_requests, limit: 500, "
        "description: Generate content requests per day limit exceeded on Free Tier."
    )
    assert _is_daily_quota_exceeded(error) is True


def test_is_daily_quota_exceeded_ignores_per_minute_limit() -> None:
    """1分あたりのレート制限は日次クォータ超過として検出しないことを確認するテスト．"""
    error = Exception(
        "429 RESOURCE_EXHAUSTED. Generate content requests per minute limit exceeded on Free Tier."
    )
    assert _is_daily_quota_exceeded(error) is False


def test_conversation_summary_out_accepts_expected_fields() -> None:
    """会話一覧レスポンスモデルが想定するフィールドを正しく受理することを確認するテスト．"""
    summary = ConversationSummaryOut(
        conversation_id="00000000-0000-0000-0000-000000000000",
        started_at="2026-01-01T09:00:00",
        ended_at="2026-01-01T09:05:00",
        participant_names=["田中", "(ab12cd34)"],
        utterance_count=12,
    )
    assert summary.utterance_count == 12
    assert summary.participant_names == ["田中", "(ab12cd34)"]


def test_update_person_name_in_accepts_name() -> None:
    """人物名の更新リクエストモデルが文字列を受理することを確認するテスト．"""
    body = UpdatePersonNameIn(name="田中")
    assert body.name == "田中"
