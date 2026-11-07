"""EchoMindサーバーのFastAPIエントリポイント．

実行方法:
    .venv_ml/bin/uvicorn app.main:app --app-dir programs/server --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from app.api import audio, auth, browse, chat, upload
from app.db.session import init_db

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にDBの初期化(拡張の有効化・テーブル作成)を行うライフサイクル関数．"""
    init_db()
    yield


app = FastAPI(title="EchoMind Server", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(browse.router)
app.include_router(audio.router)


@app.get("/health")
def health() -> dict:
    """ヘルスチェック用エンドポイント．

    引数:
        なし
    戻り値:
        response (dict): サーバーの稼働状態
    """
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """ブラウザが自動的に要求するfavicon.ico用のダミーレスポンス(404ログを抑制する)．

    引数:
        なし
    戻り値:
        response (Response): 内容を持たない204レスポンス
    """
    return Response(status_code=204)


# 静的ファイル(ブラウザ用フロントエンド)の配信．
# 上記のAPIルートが先に登録されているため，/api/*等は静的ファイル配信より優先してマッチする．
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
