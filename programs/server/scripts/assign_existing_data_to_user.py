"""既存のデバッグ用データ(user_id列追加前に作成されたConversation/Person)を，
指定したアカウントへ帰属づける一度限りの移行スクリプト．

事前に，ブラウザのアカウント登録フォーム(または `POST /api/auth/register`)で
対象のアカウントを登録しておくこと．このスクリプトはパスワードを扱わず，
既に登録されたアカウントのメールアドレスのみを受け取る．

実行方法:
    .venv_ml/bin/python programs/server/scripts/assign_existing_data_to_user.py --email admin@example.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.models import Conversation, Person, User  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def _ensure_user_id_columns_exist() -> None:
    """persons・conversationsテーブルにuser_id列が存在しない場合，追加する関数．

    アカウント機能の追加前に作成されたDBスキーマには`user_id`列が存在しないため，
    `ALTER TABLE`で追加する(`Base.metadata.create_all`は既存テーブルへの
    列追加を行わないため)．

    引数:
        なし
    戻り値:
        なし
    """
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE persons ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
        conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
        conn.commit()


def assign_existing_data_to_user(email: str) -> None:
    """user_idが未設定の既存データを，指定したメールアドレスのアカウントへ帰属づける関数．

    引数:
        email (str): 既に登録済みのアカウントのメールアドレス
    戻り値:
        なし
    """
    _ensure_user_id_columns_exist()

    session = SessionLocal()
    try:
        user = session.scalars(select(User).where(User.email == email)).first()
        if user is None:
            raise ValueError(
                f"メールアドレス「{email}」のアカウントが見つかりません．"
                "先にブラウザのアカウント登録フォームでアカウントを作成してください．"
            )

        updated_persons = session.scalars(select(Person).where(Person.user_id.is_(None))).all()
        for person in updated_persons:
            person.user_id = user.user_id

        updated_conversations = session.scalars(select(Conversation).where(Conversation.user_id.is_(None))).all()
        for conversation in updated_conversations:
            conversation.user_id = user.user_id

        user.role = "admin"

        session.commit()
        print(
            f"{len(updated_persons)}件の人物，{len(updated_conversations)}件の会話を"
            f"「{email}」(admin)に帰属づけました．"
        )
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="既存データを帰属づけるアカウントのメールアドレス")
    args = parser.parse_args()
    assign_existing_data_to_user(args.email)
