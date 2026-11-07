"""パスワードハッシュ化・JWTトークンの発行・検証を行うモジュール．"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import JWT_ALGORITHM, JWT_EXPIRES_MINUTES, get_jwt_secret
from app.db.models import User
from app.db.session import get_session

_bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    """パスワードをbcryptでハッシュ化する関数．

    引数:
        password (str): 平文のパスワード
    戻り値:
        password_hash (str): ハッシュ化されたパスワード
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """平文のパスワードがハッシュと一致するかを検証する関数．

    引数:
        password (str): 検証したい平文のパスワード
        password_hash (str): DBに保存されているハッシュ化されたパスワード
    戻り値:
        is_valid (bool): パスワードが一致するかどうか
    """
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """指定したユーザーIDに対するJWTアクセストークンを発行する関数．

    引数:
        user_id (str): ユーザーID
    戻り値:
        token (str): JWTアクセストークン
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)
    payload = {"sub": user_id, "exp": expires_at}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    """Authorizationヘッダ(Bearer Token)から現在のログインユーザーを取得する依存関数．

    APIエンドポイントで`Depends(get_current_user)`として使用し，認証を必須にする．

    引数:
        credentials (HTTPAuthorizationCredentials): Authorizationヘッダから抽出された認証情報
        session (Session): DBセッション(依存性注入)
    戻り値:
        user (User): 認証されたユーザー
    """
    try:
        payload = jwt.decode(credentials.credentials, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="認証トークンが無効です") from error

    user = session.scalars(select(User).where(User.user_id == user_id)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="認証トークンに対応するユーザーが見つかりません")
    return user
