"""音声アップロードAPI．

仕様書「3.2. サーバー側(FastAPI)の常時処理パイプライン」の入口となるエンドポイント．

クライアント(iPhoneアプリ等)が報告する録音開始時刻を信頼し，サーバーがファイルを
受け取った時刻は発言のタイムスタンプとして使用しない(通信の遅延等により，実際の
録音タイミングと誤認することを防ぐため)．また，クライアントからの応答が失われて
同じ音声が再送された場合に二重処理しないよう，受信した音声データのSHA256ハッシュを
用いて冪等性チェックを行う．
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import UPLOADED_AUDIO_DIR
from app.db.models import UploadRecord, User
from app.db.session import get_session
from app.pipeline.orchestrator import process_uploaded_audio
from app.timeutil import parse_client_datetime

router = APIRouter()

_DEFAULT_EXTENSION = ".m4a"  # クライアントはAACで送信する想定のため，拡張子不明時はこれを用いる

# "processing"のまま，この時間を超えて更新されていない記録は，サーバー再起動等で処理が
# 中断されたまま失敗記録(failed)に更新されずに残っている可能性があるとみなし，再試行を許可する
_STALE_PROCESSING_TIMEOUT = timedelta(minutes=30)

# 処理がこれ以上進まない(最終的な)状態．クライアントはこれらの状態になるまでポーリングする．
_TERMINAL_STATUSES = {"completed", "rejected", "failed"}

# サーバー側での処理が完全に終わっており，かつ再試行の予定がないため，クライアントが
# 端末上の音声ファイルを安全に削除してよい状態．
# "failed"は再試行の対象(`_is_retryable`)であり，再送のためファイルを残す必要があるため含めない．
_SAFE_TO_DELETE_STATUSES = {"completed", "rejected"}


class UploadStatusOut(BaseModel):
    """アップロードの処理状況のレスポンスモデル．

    クライアントはアップロード後にこのエンドポイントをポーリングし，
    `safe_to_delete_client_copy`が`true`になった時点で端末上の音声ファイルを削除する．
    """

    upload_record_id: str
    status: str
    is_finished: bool
    safe_to_delete_client_copy: bool
    conversation_id: str | None


def _build_upload_status(record: UploadRecord) -> UploadStatusOut:
    """アップロード記録から，クライアントに返す処理状況レスポンスを構築する関数．

    引数:
        record (UploadRecord): 対象のアップロード記録
    戻り値:
        upload_status (UploadStatusOut): 処理状況レスポンス
    """
    return UploadStatusOut(
        upload_record_id=record.upload_record_id,
        status=record.status,
        is_finished=record.status in _TERMINAL_STATUSES,
        safe_to_delete_client_copy=record.status in _SAFE_TO_DELETE_STATUSES,
        conversation_id=record.conversation_id,
    )


def _parse_recorded_started_at(value: str) -> datetime:
    """クライアントから送られた録音開始時刻の文字列(ISO8601)を解析する関数．

    引数:
        value (str): ISO8601形式の日時文字列(例: "2026-11-11T09:00:00Z")
    戻り値:
        recorded_started_at (datetime): 解析されたUTCのdatetime(タイムゾーン情報は持たない)
    """
    try:
        return parse_client_datetime(value)
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail="recorded_started_atはISO8601形式(例: 2026-11-11T09:00:00Z)で指定してください"
        ) from error


def _guess_extension(filename: str | None) -> str:
    """アップロードされたファイル名から拡張子を推定する関数．

    引数:
        filename (str | None): アップロードされたファイルの元のファイル名
    戻り値:
        extension (str): ドットを含む拡張子(例: ".m4a")
    """
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    return _DEFAULT_EXTENSION


def _is_retryable(record: UploadRecord) -> bool:
    """既存のアップロード記録が再試行の対象となるかを判定する関数．

    "failed"(処理中にエラーが発生し再試行すべき)，または"processing"のまま
    `_STALE_PROCESSING_TIMEOUT`を超えて更新されていない(サーバー異常終了等で
    処理が中断されたまま残っている可能性がある)場合に再試行を許可する．
    "completed"(処理済み)・"rejected"(会話として扱われないと判定済み)は
    再実行しても結果が変わらないため，再試行の対象としない．

    引数:
        record (UploadRecord): 既存のアップロード記録
    戻り値:
        is_retryable (bool): 再試行を許可するかどうか
    """
    if record.status == "failed":
        return True
    if record.status == "processing":
        age = datetime.utcnow() - record.created_at
        return age > _STALE_PROCESSING_TIMEOUT
    return False


def _duplicate_response(record: UploadRecord) -> dict:
    """既存のアップロード記録から，重複アップロード時のレスポンスを構築する関数．

    引数:
        record (UploadRecord): 既存のアップロード記録
    戻り値:
        response (dict): クライアントに返すレスポンス
    """
    return {
        "status": "duplicate",
        "upload_record_id": record.upload_record_id,
        "processing_status": record.status,
        "conversation_id": record.conversation_id,
        "safe_to_delete_client_copy": record.status in _SAFE_TO_DELETE_STATUSES,
    }


@router.post("/api/upload")
async def upload_audio(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    recorded_started_at: str = Form(
        ..., description="録音開始時刻(ISO8601形式．クライアントの実際の録音開始時刻を指定する)"
    ),
    client_file_id: str | None = Form(
        None, description="クライアントが発行する録音ファイルの一意なID(再送時の重複検出の補助に用いる)"
    ),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """iPhoneアプリから送信された音声ファイルを受け取り，常時処理パイプラインを起動するエンドポイント．

    引数:
        file (UploadFile): アップロードされた音声ファイル(AAC/.m4a等の軽量な圧縮形式を想定)
        background_tasks (BackgroundTasks): FastAPIのバックグラウンドタスク機構
        recorded_started_at (str): 録音開始時刻(ISO8601形式の文字列)．発言の絶対タイムスタンプの
            算出に使用する(サーバーの受信時刻ではない)．
        client_file_id (str | None) = None: クライアントが発行する録音ファイルのID．
            DB上の重複検出は音声データのSHA256ハッシュで行うため，これは補助的な記録用である．
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)．アップロードされた
            会話・人物はこのユーザーのアカウントに紐づけられる．
    戻り値:
        response (dict): 受付状況を示すメッセージ．既に処理済み(または処理中)の音声の場合は
            `status: "duplicate"`として過去の処理結果を返す．
    """
    recorded_at = _parse_recorded_started_at(recorded_started_at)

    content = await file.read()
    content_sha256 = hashlib.sha256(content).hexdigest()

    # 冪等性チェック: 同一アカウント内で同じ音声データの処理記録が既にある場合は基本的に再処理しない．
    # ただし，処理が失敗したまま，またはサーバー異常終了等で処理中のまま残っている記録は再試行を許可する．
    existing_record = session.scalars(
        select(UploadRecord).where(
            UploadRecord.user_id == current_user.user_id,
            UploadRecord.content_sha256 == content_sha256,
        )
    ).first()
    if existing_record is not None and not _is_retryable(existing_record):
        return _duplicate_response(existing_record)

    UPLOADED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    extension = _guess_extension(file.filename)
    audio_path = UPLOADED_AUDIO_DIR / f"{recorded_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{extension}"
    with open(audio_path, "wb") as f:
        f.write(content)

    if existing_record is not None:
        # 再試行: 新しい記録を作らず，既存の記録を"processing"に戻して使い回す
        existing_record.status = "processing"
        existing_record.conversation_id = None
        existing_record.client_file_id = client_file_id
        existing_record.recorded_started_at = recorded_at
        session.commit()
        upload_record = existing_record
    else:
        upload_record = UploadRecord(
            user_id=current_user.user_id,
            client_file_id=client_file_id,
            content_sha256=content_sha256,
            status="processing",
            recorded_started_at=recorded_at,
        )
        session.add(upload_record)
        try:
            session.commit()
        except IntegrityError:
            # 同じ音声データに対する並行アップロードが一意制約に同時に抵触した場合，
            # 自分の挿入は諦めて，相手(先にコミットされた方)の記録を重複として返す
            session.rollback()
            concurrent_record = session.scalars(
                select(UploadRecord).where(
                    UploadRecord.user_id == current_user.user_id,
                    UploadRecord.content_sha256 == content_sha256,
                )
            ).first()
            if concurrent_record is not None:
                return _duplicate_response(concurrent_record)
            raise

    background_tasks.add_task(
        process_uploaded_audio,
        audio_path,
        recorded_at,
        current_user.user_id,
        upload_record_id=upload_record.upload_record_id,
    )

    return {"status": "accepted", "upload_record_id": upload_record.upload_record_id}


@router.get("/api/upload/{upload_record_id}/status", response_model=UploadStatusOut)
def get_upload_status(
    upload_record_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> UploadStatusOut:
    """アップロードした音声の処理状況(終了フラグ)を取得するエンドポイント．

    サーバー側の処理はバックグラウンドで非同期に実行されるため，`POST /api/upload`の
    応答だけでは処理の完了を知ることができない．クライアントは`POST /api/upload`が
    返した`upload_record_id`を使ってこのエンドポイントを定期的にポーリングし，
    `safe_to_delete_client_copy`が`true`になった時点で端末上の音声ファイルを削除すること．

    - `status == "completed"`: 処理が正常に完了した(会話として保存された)．削除してよい．
    - `status == "rejected"`: 発話が検出されなかった，または話者が1名のみで「会話」として
      扱われなかった．再送しても結果は変わらないため削除してよい．
    - `status == "failed"`: 処理中にエラーが発生した．サーバー側で再試行可能な状態になって
      いるため，クライアントはファイルを削除せず，しばらくしてから同じファイルを再送すること．
    - `status == "processing"`: まだ処理中．しばらく待ってから再度確認すること．

    引数:
        upload_record_id (str): `POST /api/upload`のレスポンスで返されたアップロード記録ID
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        upload_status (UploadStatusOut): 処理状況
    """
    record = session.get(UploadRecord, upload_record_id)
    if record is None or record.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="指定されたアップロード記録が見つかりません")

    return _build_upload_status(record)
