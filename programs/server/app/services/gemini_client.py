"""Gemini APIクライアントのラッパーモジュール．

無料枠の1日あたりのリクエスト数上限(日次クォータ)に達した場合，次の候補モデルへ
自動的に切り替える．1分あたりのレート制限や一時的なサーバーエラーについては，
同一モデルのまま指数バックオフでリトライする．
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import load_tokens

_client: genai.Client | None = None

# 日次クォータに達した場合に切り替える候補モデル(優先順)．
# 無料枠でのGenerate Content API呼び出しが確認できた軽量モデルを先に並べる．
_MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
_current_model_index = 0


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


def _is_daily_quota_exceeded(error: genai_errors.ClientError) -> bool:
    """エラーが「1日あたりのリクエスト数上限」によるものかを判定する関数．

    1分あたりのレート制限(一時的，同一モデルでのリトライで解消する)とは区別し，
    日次クォータ超過の場合のみモデル切り替えの対象とする．

    引数:
        error (genai_errors.ClientError): Gemini APIから返されたエラー
    戻り値:
        is_daily_quota_exceeded (bool): 日次クォータ超過と判定できるかどうか
    """
    message = str(error)
    return "RESOURCE_EXHAUSTED" in message and "per day" in message


@retry(
    retry=retry_if_exception_type((genai_errors.ServerError, genai_errors.ClientError)),
    wait=wait_random_exponential(multiplier=2, max=60),
    stop=stop_after_attempt(8),
)
def generate_text(prompt: str) -> str:
    """Gemini APIへプロンプトを送信し，生成されたテキストを取得する関数．

    1分あたりのレート制限(429)や一時的なサーバーエラー(5xx)に対しては，
    同一モデルのまま指数バックオフでリトライする．1日あたりのリクエスト数上限に
    達した場合は，`_MODEL_CANDIDATES`の次のモデルへ切り替えて続行する．

    引数:
        prompt (str): Gemini APIへ送信するプロンプト
    戻り値:
        text (str): 生成されたテキスト
    """
    global _current_model_index
    client = _get_client()

    while True:
        model_name = _MODEL_CANDIDATES[_current_model_index]
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            return response.text
        except genai_errors.ClientError as error:
            if _is_daily_quota_exceeded(error) and _current_model_index < len(_MODEL_CANDIDATES) - 1:
                _current_model_index += 1
                continue
            raise
