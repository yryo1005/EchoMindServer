"""音声アップロードAPI．

仕様書「3.2. サーバー側(FastAPI)の常時処理パイプライン」の入口となるエンドポイント．
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, UploadFile

from app.config import UPLOADED_AUDIO_DIR
from app.pipeline.orchestrator import process_uploaded_audio

router = APIRouter()


@router.post("/api/upload")
async def upload_audio(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    """iPhoneアプリから送信された音声ファイルを受け取り，常時処理パイプラインを起動するエンドポイント．

    引数:
        file (UploadFile): アップロードされた音声ファイル
        background_tasks (BackgroundTasks): FastAPIのバックグラウンドタスク機構
    戻り値:
        response (dict): 受付完了を示すメッセージ
    """
    UPLOADED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    received_at = datetime.utcnow()
    audio_path = UPLOADED_AUDIO_DIR / f"{received_at:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.wav"

    with open(audio_path, "wb") as f:
        f.write(await file.read())

    background_tasks.add_task(process_uploaded_audio, audio_path, received_at)

    return {"status": "accepted", "audio_path": str(audio_path)}
