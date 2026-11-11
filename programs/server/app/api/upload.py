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
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import UPLOADED_AUDIO_DIR
from app.db.models import UploadRecord, User
from app.db.session import get_session
from app.pipeline.orchestrator import process_uploaded_audio

router = APIRouter()

_DEFAULT_EXTENSION = ".m4a"  # クライアントはAACで送信する想定のため，拡張子不明時はこれを用いる


def _parse_recorded_started_at(value: str) -> datetime:
    """クライアントから送られた録音開始時刻の文字列(ISO8601)を解析する関数．

    引数:
        value (str): ISO8601形式の日時文字列(例: "2026-11-11T09:00:00Z")
    戻り値:
        recorded_started_at (datetime): 解析された日時
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
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
        response (dict): 受付状況を示すメッセージ．既に処理済みの音声の場合は
            `status: "duplicate"`として過去の処理結果を返す．
    """
    recorded_at = _parse_recorded_started_at(recorded_started_at)

    content = await file.read()
    content_sha256 = hashlib.sha256(content).hexdigest()

    # 冪等性チェック: 同一アカウント内で同じ音声データが既に処理されている場合は再処理しない
    existing_record = session.scalars(
        select(UploadRecord).where(
            UploadRecord.user_id == current_user.user_id,
            UploadRecord.content_sha256 == content_sha256,
        )
    ).first()
    if existing_record is not None:
        return {
            "status": "duplicate",
            "upload_record_id": existing_record.upload_record_id,
            "processing_status": existing_record.status,
            "conversation_id": existing_record.conversation_id,
        }

    UPLOADED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    extension = _guess_extension(file.filename)
    audio_path = UPLOADED_AUDIO_DIR / f"{recorded_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{extension}"
    with open(audio_path, "wb") as f:
        f.write(content)

    upload_record = UploadRecord(
        user_id=current_user.user_id,
        client_file_id=client_file_id,
        content_sha256=content_sha256,
        status="processing",
        recorded_started_at=recorded_at,
    )
    session.add(upload_record)
    session.commit()

    background_tasks.add_task(
        process_uploaded_audio,
        audio_path,
        recorded_at,
        current_user.user_id,
        upload_record_id=upload_record.upload_record_id,
    )

    return {"status": "accepted", "upload_record_id": upload_record.upload_record_id}
