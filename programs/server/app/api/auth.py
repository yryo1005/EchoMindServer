"""アカウント登録・ログインAPI．"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db.models import User
from app.db.session import get_session

router = APIRouter()


class RegisterIn(BaseModel):
    """アカウント登録リクエストのモデル．"""

    email: EmailStr
    password: str


class LoginIn(BaseModel):
    """ログインリクエストのモデル．"""

    email: EmailStr
    password: str


class TokenOut(BaseModel):
    """アクセストークンのレスポンスモデル．"""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """ユーザー情報のレスポンスモデル(パスワードハッシュは含まない)．"""

    user_id: str
    email: str
    role: str


@router.post("/api/auth/register", response_model=TokenOut)
def register(body: RegisterIn, session: Session = Depends(get_session)) -> TokenOut:
    """新しいアカウントを登録するエンドポイント．

    引数:
        body (RegisterIn): 登録するメールアドレスとパスワード
        session (Session): DBセッション(依存性注入)
    戻り値:
        token (TokenOut): 登録直後に発行されるアクセストークン
    """
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="パスワードは8文字以上にしてください")

    existing_user = session.scalars(select(User).where(User.email == body.email)).first()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="このメールアドレスは既に登録されています")

    user = User(email=body.email, password_hash=hash_password(body.password), role="user")
    session.add(user)
    session.commit()

    return TokenOut(access_token=create_access_token(user.user_id))


@router.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> TokenOut:
    """メールアドレスとパスワードでログインするエンドポイント．

    引数:
        body (LoginIn): ログインするメールアドレスとパスワード
        session (Session): DBセッション(依存性注入)
    戻り値:
        token (TokenOut): アクセストークン
    """
    user = session.scalars(select(User).where(User.email == body.email)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが正しくありません")

    return TokenOut(access_token=create_access_token(user.user_id))


@router.get("/api/auth/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """現在ログイン中のユーザー情報を取得するエンドポイント．

    引数:
        current_user (User): 認証されたユーザー(依存性注入)
    戻り値:
        user (UserOut): ユーザー情報
    """
    return UserOut(user_id=current_user.user_id, email=current_user.email, role=current_user.role)
