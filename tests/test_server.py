"""EchoMindサーバーの単体テスト．

モデルのロードやDB接続を伴わない，純粋な関数のみを対象とする．
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "programs" / "server"))

from app.api.browse import ConversationSummaryOut, UpdatePersonNameIn  # noqa: E402
from app.api.upload import _guess_extension, _is_retryable, _parse_recorded_started_at  # noqa: E402
from app.auth import create_access_token, hash_password, verify_password  # noqa: E402
from app.pipeline.person_identification import _cosine_similarity  # noqa: E402
from app.services.gemini_client import _is_daily_quota_exceeded  # noqa: E402
from app.timeutil import as_utc_aware, parse_client_datetime, to_jst  # noqa: E402


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


def test_hash_password_and_verify_password_roundtrip() -> None:
    """パスワードのハッシュ化と検証が正しく対応することを確認するテスト．"""
    password_hash = hash_password("correct-password")
    assert verify_password("correct-password", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_parse_recorded_started_at_accepts_utc_z_suffix() -> None:
    """ISO8601(末尾Z)形式の録音開始時刻を解析できることを確認するテスト．"""
    parsed = _parse_recorded_started_at("2026-03-01T08:30:00Z")
    assert parsed.year == 2026
    assert parsed.month == 3
    assert parsed.day == 1
    assert parsed.hour == 8


def test_parse_recorded_started_at_rejects_invalid_format() -> None:
    """不正な形式の録音開始時刻がHTTPExceptionとして拒否されることを確認するテスト．"""
    from fastapi import HTTPException

    try:
        _parse_recorded_started_at("not-a-valid-timestamp")
        assert False, "例外が発生するはずです"
    except HTTPException as error:
        assert error.status_code == 400


def test_guess_extension_uses_filename_suffix() -> None:
    """アップロードファイル名から拡張子を正しく推定できることを確認するテスト．"""
    assert _guess_extension("recording.aac") == ".aac"
    assert _guess_extension("recording.m4a") == ".m4a"


def test_guess_extension_falls_back_to_m4a_when_missing() -> None:
    """拡張子が不明な場合，デフォルトの.m4aが使われることを確認するテスト．"""
    assert _guess_extension(None) == ".m4a"
    assert _guess_extension("recording_without_extension") == ".m4a"


def test_is_retryable_allows_failed_records() -> None:
    """"failed"状態の記録が再試行可能と判定されることを確認するテスト．"""
    from datetime import datetime
    from types import SimpleNamespace

    record = SimpleNamespace(status="failed", created_at=datetime.utcnow())
    assert _is_retryable(record) is True


def test_is_retryable_blocks_completed_and_rejected_records() -> None:
    """"completed"・"rejected"状態の記録は再試行対象にならないことを確認するテスト．"""
    from datetime import datetime
    from types import SimpleNamespace

    assert _is_retryable(SimpleNamespace(status="completed", created_at=datetime.utcnow())) is False
    assert _is_retryable(SimpleNamespace(status="rejected", created_at=datetime.utcnow())) is False


def test_is_retryable_blocks_recent_processing_records() -> None:
    """直近の"processing"状態の記録は(処理中の可能性があるため)再試行対象にならないことを確認するテスト．"""
    from datetime import datetime
    from types import SimpleNamespace

    record = SimpleNamespace(status="processing", created_at=datetime.utcnow())
    assert _is_retryable(record) is False


def test_is_retryable_allows_stale_processing_records() -> None:
    """タイムアウトを超えて"processing"のまま残っている記録は再試行可能と判定されることを確認するテスト．"""
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    record = SimpleNamespace(status="processing", created_at=datetime.utcnow() - timedelta(hours=1))
    assert _is_retryable(record) is True


def test_parse_client_datetime_normalizes_to_naive_utc() -> None:
    """タイムゾーン付きの日時文字列が，タイムゾーン情報を持たないUTCに正規化されることを確認するテスト．"""
    parsed = parse_client_datetime("2026-03-01T17:30:00+09:00")
    assert parsed.tzinfo is None
    assert parsed.hour == 8  # 17:30 JST(+09:00) = 08:30 UTC
    assert parsed.minute == 30


def test_as_utc_aware_attaches_utc_timezone() -> None:
    """naiveなdatetimeにUTCのtzinfoが付与されることを確認するテスト．"""
    from datetime import datetime, timezone

    naive = datetime(2026, 3, 1, 8, 30, 0)
    aware = as_utc_aware(naive)
    assert aware.tzinfo == timezone.utc
    assert aware.isoformat() == "2026-03-01T08:30:00+00:00"


def test_to_jst_converts_utc_to_jst() -> None:
    """UTCの時刻が日本時間(UTC+9)に正しく変換されることを確認するテスト．"""
    from datetime import datetime

    naive_utc = datetime(2026, 3, 1, 8, 30, 0)
    jst = to_jst(naive_utc)
    assert jst.hour == 17
    assert jst.minute == 30


def test_create_access_token_contains_user_id() -> None:
    """発行したJWTアクセストークンから元のユーザーIDを復元できることを確認するテスト．"""
    import jwt as pyjwt

    from app.config import JWT_ALGORITHM, get_jwt_secret

    token = create_access_token("00000000-0000-0000-0000-000000000000")
    payload = pyjwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "00000000-0000-0000-0000-000000000000"
