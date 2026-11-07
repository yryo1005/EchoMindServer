"""話者ID統合・名前推定モジュール．

仕様書の「話者IDの統合」「名前推定」に対応する．pyannoteが会話ごとに付与する
一時的な話者ラベル(例: "SPEAKER_00")を，256次元の話者埋め込みの類似度に基づき，
DB全体で一意な人物ID(Person)へ統合する．また，発話数が十分多い人物については，
会話内容からGemini APIを用いて名前を推定する．
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import NAME_ESTIMATION_MIN_UTTERANCE_COUNT, SPEAKER_MATCH_THRESHOLD
from app.db.models import Person, Utterance
from app.services.gemini_client import generate_text


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """2つのベクトルのコサイン類似度を計算する関数．

    引数:
        a (np.ndarray): shape=(d,)のベクトル
        b (np.ndarray): shape=(d,)のベクトル
    戻り値:
        similarity (float): コサイン類似度(-1.0〜1.0)
    """
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def resolve_person(session: Session, speaker_embedding: np.ndarray, user_id: str) -> Person:
    """話者埋め込みから対応するPersonを取得する(なければ新規作成する)関数．

    話者の照合は同一アカウント(user_id)内の人物に限定する(他ユーザーの人物と
    誤って統合されないようにするため)．

    引数:
        session (Session): DBセッション
        speaker_embedding (np.ndarray): shape=(256,)の話者埋め込み
        user_id (str): 話者が属するアカウントのユーザーID
    戻り値:
        person (Person): 対応するPerson(既存または新規作成)
    """
    existing_persons = session.scalars(select(Person).where(Person.user_id == user_id)).all()

    best_person = None
    best_similarity = -1.0
    for person in existing_persons:
        if person.representative_embedding is None:
            continue
        similarity = _cosine_similarity(speaker_embedding, np.array(person.representative_embedding))
        if similarity > best_similarity:
            best_similarity = similarity
            best_person = person

    if best_person is not None and best_similarity >= SPEAKER_MATCH_THRESHOLD:
        return best_person

    new_person = Person(user_id=user_id, representative_embedding=speaker_embedding.tolist())
    session.add(new_person)
    session.flush()
    return new_person


def estimate_name_from_context(context_lines: list[str]) -> str:
    """会話コンテキスト(テキスト)からGemini APIを用いて名前を推定する純粋関数．

    DBに依存しないため，`programs/ex003_server_evaluation/`での精度検証に直接再利用できる．

    引数:
        context_lines (list[str]): 会話の各発言．名前推定の対象とする発言には
            先頭に"[対象人物]"を付与しておく．
    戻り値:
        estimated_name (str): 推定された名前．特定できない場合は"不明"．
    """
    context_text = "\n".join(context_lines)
    prompt = (
        "以下は複数人の会話記録です．[対象人物]とマークされた発言を行った人物の名前を，"
        "会話内の呼びかけや自己紹介等から推定してください．"
        "名前が特定できない場合は「不明」の一語のみを出力してください．"
        "特定できる場合は，名前のみを出力してください(説明は不要)．\n\n"
        f"{context_text}"
    )
    result = generate_text(prompt)
    return result.strip() if result else "不明"


def maybe_estimate_name(session: Session, person: Person) -> None:
    """登場頻度の高い人物について，会話文脈から名前を推定する関数．

    引数:
        session (Session): DBセッション
        person (Person): 名前推定の対象とする人物
    戻り値:
        なし
    """
    if person.name is not None:
        return
    if person.utterance_count < NAME_ESTIMATION_MIN_UTTERANCE_COUNT:
        return

    recent_utterances = session.scalars(
        select(Utterance)
        .where(Utterance.conversation_id.in_(
            select(Utterance.conversation_id).where(Utterance.person_id == person.person_id).distinct()
        ))
        .order_by(Utterance.start_time.desc())
        .limit(50)
    ).all()

    context_lines = [
        f"{'[対象人物]' if u.person_id == person.person_id else ''}{u.text}" for u in recent_utterances
    ]
    estimated_name = estimate_name_from_context(context_lines)

    if estimated_name and estimated_name != "不明":
        person.name = estimated_name
        session.add(person)
