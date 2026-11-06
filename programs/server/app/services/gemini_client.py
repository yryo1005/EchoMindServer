"""Gemini APIクライアントのラッパーモジュール．"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import load_tokens

_client: genai.Client | None = None
_MODEL_NAME = "gemini-3.1-flash-lite"


def _get_client() -> genai.Client:
    """Gemini APIクライアントを初期化(初回のみ)して返す関数．

    引数:
        なし
    戻り値:
        client (genai.Client): Gemini APIクライアント
    """
    global _client
    if _client is None:
        api_key = load_tokens()["gemini"]
        _client = genai.Client(api_key=api_key)
    return _client


@retry(
    retry=retry_if_exception_type((genai_errors.ServerError, genai_errors.ClientError)),
    wait=wait_random_exponential(multiplier=2, max=60),
    stop=stop_after_attempt(8),
)
def generate_text(prompt: str) -> str:
    """Gemini APIへプロンプトを送信し，生成されたテキストを取得する関数．

    無料枠のレート制限(429)や一時的なサーバーエラー(5xx)に対しては，
    指数バックオフでリトライする．

    引数:
        prompt (str): Gemini APIへ送信するプロンプト
    戻り値:
        text (str): 生成されたテキスト
    """
    client = _get_client()
    response = client.models.generate_content(model=_MODEL_NAME, contents=prompt)
    return response.text
