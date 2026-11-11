"""日時のタイムゾーン変換ユーティリティ．

DBのdatetime列はタイムゾーン情報を持たない(naive)が，アプリ全体の規約として
「保存されている値は常にUTC」として扱う．この規約を一箇所にまとめ，クライアントからの
入力の解析，APIレスポンスでのUTC明示，日本時間(JST)表示への変換を提供する．
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def parse_client_datetime(value: str) -> datetime:
    """クライアントから送られたISO8601形式の日時文字列を解析し，naiveなUTCのdatetimeに変換する関数．

    タイムゾーン情報(例: 末尾の"Z"や"+09:00")が含まれる場合はUTCへ変換した上でtzinfoを外す．
    タイムゾーン情報が含まれない場合は，既にUTCであるとみなす．

    引数:
        value (str): ISO8601形式の日時文字列(例: "2026-11-11T09:00:00Z")
    戻り値:
        naive_utc (datetime): タイムゾーン情報を持たないUTCのdatetime
    戻り値の例外:
        ValueError: valueがISO8601形式として解析できない場合
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def as_utc_aware(naive_utc: datetime) -> datetime:
    """DBに保存されているnaiveなUTCのdatetimeに，明示的にUTCのtzinfoを付与する関数．

    APIレスポンスとしてシリアライズする直前に適用することで，クライアント側が
    タイムゾーンを誤って解釈すること(naiveな値をローカル時刻だと誤認する等)を防ぐ．

    引数:
        naive_utc (datetime): タイムゾーン情報を持たないUTCのdatetime
    戻り値:
        aware_utc (datetime): tzinfo=UTCを付与したdatetime
    """
    return naive_utc.replace(tzinfo=timezone.utc)


def to_jst(naive_utc: datetime) -> datetime:
    """DBに保存されているnaiveなUTCのdatetimeを，日本時間(JST, UTC+9)に変換する関数．

    引数:
        naive_utc (datetime): タイムゾーン情報を持たないUTCのdatetime
    戻り値:
        jst_datetime (datetime): JSTに変換されたdatetime(tzinfo付き)
    """
    return as_utc_aware(naive_utc).astimezone(JST)


def now_jst() -> datetime:
    """現在時刻を日本時間(JST)で取得する関数．

    引数:
        なし
    戻り値:
        jst_now (datetime): 現在の日本時間(tzinfo付き)
    """
    return datetime.now(timezone.utc).astimezone(JST)
