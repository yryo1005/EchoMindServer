"""質問応答(QA)API．

仕様書「3.3. ユーザーからの質問(QA)フロー」に対応する．
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Utterance
from app.db.session import get_session
from app.pipeline import embedding
from app.services.gemini_client import generate_text

router = APIRouter()

TOP_K = 5
CONTEXT_WINDOW = 2  # 該当発話の前後何発話を会話コンテキストとして含めるか


class ChatRequest(BaseModel):
    """/api/chatのリクエストボディ．"""

    user_id: str
    query: str


class ChatResponse(BaseModel):
    """/api/chatのレスポンスボディ．"""

    answer: str
    references: list[str]


def _search_relevant_utterances(session: Session, query_embedding, top_k: int) -> list[Utterance]:
    """質問文のベクトルに基づき，類似度が高い発話を検索する関数．

    引数:
        session (Session): DBセッション
        query_embedding: shape=(1024,)の質問文ベクトル
        top_k (int): 取得する件数
    戻り値:
        utterances (list[Utterance]): 類似度が高い順の発話リスト
    """
    stmt = select(Utterance).order_by(Utterance.embedding.cosine_distance(query_embedding)).limit(top_k)
    return list(session.scalars(stmt))


def _expand_with_context(session: Session, utterances: list[Utterance]) -> list[Utterance]:
    """検索された発話の前後数発話を同一会話から取得し，会話コンテキストを補う関数．

    引数:
        session (Session): DBセッション
        utterances (list[Utterance]): 検索された発話のリスト
    戻り値:
        context_utterances (list[Utterance]): タイムスタンプ順に並べた，コンテキストを含む発話リスト
    """
    collected: dict[str, Utterance] = {}
    for utterance in utterances:
        conversation_utterances = list(
            session.scalars(
                select(Utterance)
                .where(Utterance.conversation_id == utterance.conversation_id)
                .order_by(Utterance.start_time)
            )
        )
        index = next(i for i, u in enumerate(conversation_utterances) if u.utterance_id == utterance.utterance_id)
        start = max(0, index - CONTEXT_WINDOW)
        end = min(len(conversation_utterances), index + CONTEXT_WINDOW + 1)
        for u in conversation_utterances[start:end]:
            collected[u.utterance_id] = u

    return sorted(collected.values(), key=lambda u: u.start_time)


def _build_answer_prompt(query: str, context_utterances: list[Utterance]) -> str:
    """回答生成用のプロンプトを構築する関数．

    引数:
        query (str): ユーザーからの質問文
        context_utterances (list[Utterance]): 根拠として提示する発話のリスト
    戻り値:
        prompt (str): Gemini APIへ送信するプロンプト
    """
    context_lines = [
        f"[{u.start_time:%Y-%m-%d %H:%M}] {u.person.name or u.person_id}: {u.text}" for u in context_utterances
    ]
    context_text = "\n".join(context_lines)
    return (
        "以下は過去の会話記録の抜粋です．この会話記録のみに基づいて，質問に回答してください．"
        "会話記録から回答できない場合は，その旨を述べてください．\n\n"
        f"【会話記録】\n{context_text}\n\n"
        f"【質問】\n{query}"
    )


@router.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    """過去の会話記録に基づいて質問に回答するエンドポイント．

    引数:
        request (ChatRequest): user_idとqueryを含むリクエスト
        session (Session): DBセッション(依存性注入)
    戻り値:
        response (ChatResponse): 回答テキストと参照タイムスタンプ
    """
    query_embedding = embedding.embed_query(request.query)

    top_utterances = _search_relevant_utterances(session, query_embedding, TOP_K)
    context_utterances = _expand_with_context(session, top_utterances)

    prompt = _build_answer_prompt(request.query, context_utterances)
    answer = generate_text(prompt).strip()

    references = [u.start_time.isoformat() for u in top_utterances]
    return ChatResponse(answer=answer, references=references)
