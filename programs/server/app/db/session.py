"""データベース接続・セッション管理．"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL
from app.db.models import Base

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """pgvector拡張の有効化とテーブルの作成を行う関数．

    引数:
        なし
    戻り値:
        なし
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPIの依存性注入で使用するDBセッションを提供する関数．

    引数:
        なし
    戻り値:
        session (Generator[Session, None, None]): SQLAlchemyセッション
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
