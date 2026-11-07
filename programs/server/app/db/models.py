"""EchoMindサーバーのデータベースモデル定義．

仕様書の「4. データベース設計の要点」に基づき，「会話」の中に複数の「発言」が紐づく
階層構造を持たせる．各発言には，全体で一意の人物IDとタイムスタンプを必ず付与する．

アカウント機能(メールアドレス+パスワードでのログイン)の追加により，人物(Person)・会話
(Conversation)はアカウント(User)に紐づけ，ユーザーごとにデータを分離する．
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIM


class Base(DeclarativeBase):
    """全モデル共通のベースクラス．"""


class User(Base):
    """アカウント(メールアドレス+パスワードでログインするユーザー)を表すテーブル．

    `role`は"admin"または"user"のいずれか．既存のデバッグ用データは，移行スクリプト
    (`scripts/assign_existing_data_to_user.py`)によって"admin"ロールのアカウントに
    帰属づけられる．
    """

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    persons: Mapped[list["Person"]] = relationship(back_populates="user")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Person(Base):
    """アカウント内で一意となる「人物」を表すテーブル．

    pyannoteが会話ごとに付与する一時的な話者IDは，話者埋め込みの類似度に基づいて
    (同一アカウント内の人物の中から)このPersonへ統合される．
    """

    __tablename__ = "persons"

    person_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    representative_embedding: Mapped[list[float] | None] = mapped_column(Vector(256), nullable=True)
    utterance_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="persons")
    utterances: Mapped[list["Utterance"]] = relationship(back_populates="person")


class Conversation(Base):
    """「会話」単位を表すテーブル．複数の発言(Utterance)が紐づく．"""

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime)
    source_audio_path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="conversations")
    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="conversation", order_by="Utterance.start_time"
    )


class Utterance(Base):
    """「発言」単位を表すテーブル．会話(Conversation)に紐づく最小単位．

    「いつ」「誰が」発言した内容かをキーとした効率的な絞り込み検索を可能にするため，
    `person_id`と`start_time`を必ず持つ．
    """

    __tablename__ = "utterances"

    utterance_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.conversation_id"))
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.person_id"))

    temp_speaker_label: Mapped[str] = mapped_column(String(64))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[str] = mapped_column(Text)
    audio_path: Mapped[str] = mapped_column(String(1024))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    speaker_embedding: Mapped[list[float] | None] = mapped_column(Vector(256), nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="utterances")
    person: Mapped[Person] = relationship(back_populates="utterances")
