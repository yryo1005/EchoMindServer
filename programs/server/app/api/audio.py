"""発言の音声クリップを配信するAPI．"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db.models import User, Utterance
from app.db.session import get_session

router = APIRouter()


@router.get("/api/audio/{utterance_id}")
def get_audio(
    utterance_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """指定した発言の音声クリップを返すエンドポイント．

    自分のアカウントの発言以外は，発言の存在を含めて404として扱う(存在の有無を
    他アカウントに漏らさないため)．

    引数:
        utterance_id (str): 発言ID
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        response (FileResponse): 音声ファイル(AAC/.m4a形式で保存されている)
    """
    utterance = session.get(Utterance, utterance_id)
    if utterance is None or utterance.conversation.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="指定された発言が見つかりません")

    audio_path = Path(utterance.audio_path)
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="音声ファイルが見つかりません")

    media_type = "audio/mp4" if audio_path.suffix == ".m4a" else "audio/wav"
    return FileResponse(audio_path, media_type=media_type)
