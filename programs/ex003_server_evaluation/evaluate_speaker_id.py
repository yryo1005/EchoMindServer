"""話者ID統合の精度検証スクリプト．

`data_speaker_id.py`で生成した複数セッションを，実際のサーバーパイプライン
(`programs/server/app/pipeline/orchestrator.py`)に順次通し，DBに記録された
人物ID(Person)が，正解の話者ID(JVSラベル)とどの程度一致するかを検証する．

評価には本番用DB(`echomind`)とは別の評価用DB(`echomind_eval`)を使用する
(事前に`CREATE DATABASE echomind_eval`を実行しておくこと)．
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from app.db.models import Base, Conversation, User, Utterance  # noqa: E402
from app.pipeline.orchestrator import process_uploaded_audio  # noqa: E402

SESSIONS_DIR = Path("datasets/ex003_server_evaluation/speaker_id_sessions")
OUTPUT_DIR = Path("outputs/ex003_server_evaluation/speaker_id")
EVAL_DATABASE_URL = "postgresql+psycopg2://echomind:echomind@localhost:5432/echomind_eval"


def _reset_eval_database() -> sessionmaker:
    """評価用DBのテーブルを初期化し，セッションファクトリを返す関数．

    引数:
        なし
    戻り値:
        session_factory (sessionmaker): 評価用DBに接続するセッションファクトリ
    """
    engine = create_engine(EVAL_DATABASE_URL)
    with engine.connect() as conn:
        from sqlalchemy import text

        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _create_eval_user(session_factory: sessionmaker) -> str:
    """評価用DBに，この検証専用のダミーユーザーを作成する関数．

    アカウント機能の追加により会話・人物がユーザーに紐づくようになったため，
    評価用DBにも検証用のユーザーを1件用意する必要がある．

    引数:
        session_factory (sessionmaker): 評価用DBに接続するセッションファクトリ
    戻り値:
        user_id (str): 作成したユーザーのID
    """
    session = session_factory()
    try:
        user = User(email="ex003-speaker-id-eval@example.com", password_hash="unused", role="user")
        session.add(user)
        session.commit()
        return user.user_id
    finally:
        session.close()


def _true_speaker_for_utterance(
    utterance_start: float, utterance_end: float, ground_truth: list[dict]
) -> str | None:
    """予測された発話区間に最も時間的に重なる正解区間の話者IDを求める関数．

    話者分離の結果，発話の切れ目は正解データの発話境界と完全には一致しないため，
    重なり時間が最大となる正解区間の話者を「正解」として採用する．

    引数:
        utterance_start (float): 予測された発話の開始時刻[秒](会話開始を0とする相対時刻)
        utterance_end (float): 予測された発話の終了時刻[秒]
        ground_truth (list[dict]): 正解の発話区間リスト(start, end, true_speaker_idを含む)
    戻り値:
        true_speaker_id (str | None): 最も重なりが大きい正解話者ID．重なりがない場合はNone
    """
    best_speaker = None
    best_overlap = 0.0
    for gt in ground_truth:
        overlap = max(0.0, min(utterance_end, gt["end"]) - max(utterance_start, gt["start"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = gt["true_speaker_id"]
    return best_speaker


def _compute_purity_metrics(pairs: list[tuple[str, str]]) -> dict:
    """(正解話者ID, 予測人物ID)の対応リストから純度指標を計算する関数．

    引数:
        pairs (list[tuple[str, str]]): (true_speaker_id, predicted_person_id)のリスト
    戻り値:
        metrics (dict): person_purity(予測人物ごとの正解話者の一致率の平均)，
            speaker_recall(正解話者ごとの多数派人物IDへの集約率の平均)，
            n_true_speakers，n_predicted_personsを含む辞書
    """
    from collections import Counter, defaultdict

    person_to_true: dict[str, Counter] = defaultdict(Counter)
    true_to_person: dict[str, Counter] = defaultdict(Counter)
    for true_speaker, person_id in pairs:
        person_to_true[person_id][true_speaker] += 1
        true_to_person[true_speaker][person_id] += 1

    n_total = len(pairs)
    person_purity = sum(counter.most_common(1)[0][1] for counter in person_to_true.values()) / n_total
    speaker_recall = sum(counter.most_common(1)[0][1] for counter in true_to_person.values()) / n_total

    return {
        "person_purity": person_purity,
        "speaker_recall": speaker_recall,
        "n_true_speakers": len(true_to_person),
        "n_predicted_persons": len(person_to_true),
    }


def main() -> None:
    """全セッションをパイプラインで処理し，話者ID統合の精度を評価する関数．

    引数:
        なし
    戻り値:
        なし
    """
    session_factory = _reset_eval_database()
    eval_user_id = _create_eval_user(session_factory)

    metadata_paths = sorted(SESSIONS_DIR.glob("session_*.json"))
    base_time = datetime(2026, 1, 1, 9, 0, 0)

    for i, metadata_path in enumerate(metadata_paths):
        wav_path = metadata_path.with_suffix(".wav")
        # 各セッションが別々の録音(時間的に離れたアップロード)であることを模すため，
        # セッションごとに十分な時間差を設ける
        recorded_at = base_time + timedelta(hours=i)
        # 本検証は話者ID統合(話者分離+話者埋め込みの類似度)の精度のみを対象とするため，
        # Gemini APIを使う文章校正・名前推定は無効化し，無料枠のクォータを節約する
        process_uploaded_audio(
            wav_path,
            recorded_at,
            eval_user_id,
            session_factory=session_factory,
            enable_correction=False,
            enable_name_estimation=False,
        )

    session = session_factory()
    try:
        pairs: list[tuple[str, str]] = []
        for i, metadata_path in enumerate(metadata_paths):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            ground_truth = metadata["utterances"]
            recorded_at = base_time + timedelta(hours=i)

            conversation = session.scalars(
                select(Conversation).where(Conversation.source_audio_path == str(metadata_path.with_suffix(".wav")))
            ).first()
            if conversation is None:
                # VADまたは話者分離の結果，「会話」として扱われなかったセッション
                continue

            conv_utterances = session.scalars(
                select(Utterance).where(Utterance.conversation_id == conversation.conversation_id)
            ).all()
            for utterance in conv_utterances:
                # 発話の絶対タイムスタンプ(recorded_at + segment.start)から，
                # 正解データと同じ基準(会話音声ファイル先頭を0とする相対時刻)に変換する
                rel_start = (utterance.start_time - recorded_at).total_seconds()
                rel_end = (utterance.end_time - recorded_at).total_seconds()
                true_speaker = _true_speaker_for_utterance(rel_start, rel_end, ground_truth)
                if true_speaker is not None:
                    pairs.append((true_speaker, utterance.person_id))

        metrics = _compute_purity_metrics(pairs)
    finally:
        session.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(metrics)


if __name__ == "__main__":
    main()
