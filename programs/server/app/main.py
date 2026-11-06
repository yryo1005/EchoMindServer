"""EchoMindサーバーのFastAPIエントリポイント．

実行方法:
    .venv_ml/bin/uvicorn app.main:app --app-dir programs/server --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import chat, upload
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にDBの初期化(拡張の有効化・テーブル作成)を行うライフサイクル関数．"""
    init_db()
    yield


app = FastAPI(title="EchoMind Server", lifespan=lifespan)
app.include_router(upload.router)
app.include_router(chat.router)


@app.get("/health")
def health() -> dict:
    """ヘルスチェック用エンドポイント．

    引数:
        なし
    戻り値:
        response (dict): サーバーの稼働状態
    """
    return {"status": "ok"}
