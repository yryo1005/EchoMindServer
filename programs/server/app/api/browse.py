"""過去の会話・発言を閲覧するためのAPI．

ブラウザ用フロントエンド(`static/`)から，会話一覧・発言一覧・話者一覧を取得するために使用する．
全てのエンドポイントは認証を必須とし，自分のアカウントのデータのみを対象とする．
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db.models import Conversation, Person, User, Utterance
from app.db.session import get_session
from app.timeutil import as_utc_aware

router = APIRouter()


class PersonOut(BaseModel):
    """人物情報のレスポンスモデル．"""

    person_id: str
    name: str | None
    utterance_count: int


class UpdatePersonNameIn(BaseModel):
    """人物名の更新リクエストモデル．"""

    name: str


class ConversationSummaryOut(BaseModel):
    """会話一覧表示用のレスポンスモデル．"""

    conversation_id: str
    started_at: datetime
    ended_at: datetime
    participant_names: list[str]
    utterance_count: int


class UtteranceOut(BaseModel):
    """発言のレスポンスモデル．"""

    utterance_id: str
    person_id: str
    person_name: str | None
    start_time: datetime
    end_time: datetime
    text: str
    audio_url: str


class ConversationDetailOut(BaseModel):
    """会話詳細(発言一覧を含む)のレスポンスモデル．"""

    conversation_id: str
    started_at: datetime
    ended_at: datetime
    utterances: list[UtteranceOut]


def _utterance_to_out(utterance: Utterance) -> UtteranceOut:
    """UtteranceモデルをレスポンスモデルUtteranceOutへ変換する関数．

    引数:
        utterance (Utterance): DBモデルの発言
    戻り値:
        utterance_out (UtteranceOut): レスポンス用の発言
    """
    return UtteranceOut(
        utterance_id=utterance.utterance_id,
        person_id=utterance.person_id,
        person_name=utterance.person.name,
        start_time=as_utc_aware(utterance.start_time),
        end_time=as_utc_aware(utterance.end_time),
        text=utterance.text,
        audio_url=f"/api/audio/{utterance.utterance_id}",
    )


@router.get("/api/persons", response_model=list[PersonOut])
def list_persons(
    session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
) -> list[PersonOut]:
    """自分のアカウントに登録されている人物の一覧を取得するエンドポイント(発話数の多い順)．

    引数:
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        persons (list[PersonOut]): 人物一覧
    """
    persons = session.scalars(
        select(Person).where(Person.user_id == current_user.user_id).order_by(Person.utterance_count.desc())
    ).all()
    return [
        PersonOut(person_id=p.person_id, name=p.name, utterance_count=p.utterance_count) for p in persons
    ]


@router.put("/api/persons/{person_id}/name", response_model=PersonOut)
def update_person_name(
    person_id: str,
    body: UpdatePersonNameIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PersonOut:
    """人物の名前を手動で設定・変更するエンドポイント．

    Gemini APIによる自動の名前推定(`maybe_estimate_name`)で名前が特定できない場合に，
    ブラウザフロントエンドから手動で名前を設定できるようにするためのものである．

    引数:
        person_id (str): 人物ID
        body (UpdatePersonNameIn): 設定する名前を含むリクエストボディ
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        person (PersonOut): 更新後の人物情報
    """
    person = session.get(Person, person_id)
    if person is None or person.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="指定された人物が見つかりません")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名前を空にすることはできません")

    person.name = name
    session.commit()
    return PersonOut(person_id=person.person_id, name=person.name, utterance_count=person.utterance_count)


@router.get("/api/conversations", response_model=list[ConversationSummaryOut])
def list_conversations(
    limit: int = 20,
    offset: int = 0,
    person_id: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ConversationSummaryOut]:
    """自分のアカウントの会話の一覧を取得するエンドポイント(開始時刻の新しい順)．

    引数:
        limit (int) = 20: 取得する件数
        offset (int) = 0: スキップする件数(ページネーション用)
        person_id (str | None) = None: 指定した場合，この人物が参加した会話のみに絞り込む
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        conversations (list[ConversationSummaryOut]): 会話一覧
    """
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == current_user.user_id)
        .order_by(Conversation.started_at.desc())
    )
    if person_id is not None:
        stmt = stmt.where(
            Conversation.conversation_id.in_(
                select(Utterance.conversation_id).where(Utterance.person_id == person_id).distinct()
            )
        )
    conversations = session.scalars(stmt.limit(limit).offset(offset)).all()

    results = []
    for conversation in conversations:
        utterances = session.scalars(
            select(Utterance).where(Utterance.conversation_id == conversation.conversation_id)
        ).all()
        participant_names = sorted(
            {u.person.name or f"({u.person_id[:8]})" for u in utterances}
        )
        results.append(
            ConversationSummaryOut(
                conversation_id=conversation.conversation_id,
                started_at=as_utc_aware(conversation.started_at),
                ended_at=as_utc_aware(conversation.ended_at),
                participant_names=participant_names,
                utterance_count=len(utterances),
            )
        )
    return results


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ConversationDetailOut:
    """指定した会話の詳細(発言一覧)を取得するエンドポイント．

    引数:
        conversation_id (str): 会話ID
        session (Session): DBセッション(依存性注入)
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        conversation (ConversationDetailOut): 会話の詳細
    """
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="指定された会話が見つかりません")

    utterances = session.scalars(
        select(Utterance)
        .where(Utterance.conversation_id == conversation_id)
        .order_by(Utterance.start_time)
    ).all()

    return ConversationDetailOut(
        conversation_id=conversation.conversation_id,
        started_at=as_utc_aware(conversation.started_at),
        ended_at=as_utc_aware(conversation.ended_at),
        utterances=[_utterance_to_out(u) for u in utterances],
    )
