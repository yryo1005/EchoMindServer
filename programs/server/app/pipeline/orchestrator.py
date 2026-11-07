"""音声アップロード後の常時処理パイプライン全体を統括するモジュール．

仕様書「3.2. サーバー側(FastAPI)の常時処理パイプライン」のSTEP1〜5に対応する．
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import librosa
from sqlalchemy.orm import Session

from app.config import SAMPLE_RATE, UTTERANCE_AUDIO_DIR
from app.db.models import Conversation, Utterance
from app.db.session import SessionLocal
from app.pipeline import asr, correction, diarization, embedding, segment, vad
from app.pipeline.person_identification import maybe_estimate_name, resolve_person

# 専門用語辞書(初期プロンプト相当)．実際の運用では外部設定ファイル等から読み込む．
DOMAIN_TERMS: dict[str, list[str]] = {}


def process_uploaded_audio(
    audio_path: Path,
    recorded_at: datetime,
    user_id: str,
    session_factory: Callable[[], Session] = SessionLocal,
    enable_correction: bool = True,
    enable_name_estimation: bool = True,
) -> None:
    """アップロードされた音声ファイルに対し，常時処理パイプラインを実行する関数．

    引数:
        audio_path (Path): アップロードされた音声ファイルのパス
        recorded_at (datetime): 録音開始時刻(発言の絶対タイムスタンプ算出に使用)
        user_id (str): アップロードを行ったアカウントのユーザーID．
            会話・人物をこのアカウントに紐づけ，他アカウントのデータと分離するために使用する．
        session_factory (Callable[[], Session]) = SessionLocal: DBセッションの生成関数．
            `programs/ex003_server_evaluation/`での精度検証時に，本番用DBと異なる
            評価用DBへ向けるために上書きできる．
        enable_correction (bool) = True: Gemini APIによる文章校正(STEP4)を行うかどうか．
            `programs/ex003_server_evaluation/evaluate_speaker_id.py`のように，
            話者ID統合のみを検証したい場合にAPI呼び出しを抑制するためFalseにできる．
        enable_name_estimation (bool) = True: 名前推定を行うかどうか．用途はenable_correctionと同様．
    戻り値:
        なし
    """
    audio, _ = librosa.load(str(audio_path), sr=SAMPLE_RATE, mono=True)

    # STEP 1: 音声区間抽出(VAD) — 発話が存在する区間のみを以降の処理対象とする
    speech_segments = vad.extract_speech_segments(audio)
    if not speech_segments:
        return

    # STEP 2: 話者分離
    speaker_segments, speaker_embeddings = diarization.diarize(audio_path)
    if len({s.temp_speaker_label for s in speaker_segments}) < 2:
        # 複数の人物によるやり取りが確認できない場合は「会話」として扱わない
        return

    # STEP 3: 音声単位に切り出し
    conversation_id_dir = UTTERANCE_AUDIO_DIR / audio_path.stem
    clip_paths = segment.cut_utterance_clips(audio, speaker_segments, conversation_id_dir)

    session = session_factory()
    try:
        started_at = recorded_at + timedelta(seconds=speaker_segments[0].start)
        ended_at = recorded_at + timedelta(seconds=speaker_segments[-1].end)
        conversation = Conversation(
            user_id=user_id,
            started_at=started_at,
            ended_at=ended_at,
            source_audio_path=str(audio_path),
        )
        session.add(conversation)
        session.flush()

        temp_label_to_person = {
            temp_label: resolve_person(session, speaker_embeddings[temp_label], user_id)
            for temp_label in speaker_embeddings
        }

        # STEP 4: 音声認識 — 発話ごとに実行する(ASRはローカルモデルのためAPIコール数は問題にならない)
        raw_texts = [asr.transcribe(clip_path, domain_terms=DOMAIN_TERMS) for clip_path in clip_paths]

        # 文章校正は会話全体をまとめて1回のGemini API呼び出しで行い，APIコール数(トークン消費)を抑える
        corrected_texts = correction.correct_texts(raw_texts) if enable_correction else raw_texts

        for speaker_segment, clip_path, corrected_text in zip(speaker_segments, clip_paths, corrected_texts):
            # ベクトル化(ローカルモデル)
            text_embedding = embedding.embed_passage(corrected_text)

            person = temp_label_to_person[speaker_segment.temp_speaker_label]
            person.utterance_count += 1

            # STEP 5: データベース(DB)への保存
            utterance = Utterance(
                conversation_id=conversation.conversation_id,
                person_id=person.person_id,
                temp_speaker_label=speaker_segment.temp_speaker_label,
                start_time=recorded_at + timedelta(seconds=speaker_segment.start),
                end_time=recorded_at + timedelta(seconds=speaker_segment.end),
                text=corrected_text,
                audio_path=str(clip_path),
                embedding=text_embedding.tolist(),
                speaker_embedding=speaker_embeddings[speaker_segment.temp_speaker_label].tolist(),
            )
            session.add(utterance)

        session.flush()
        if enable_name_estimation:
            for person in temp_label_to_person.values():
                maybe_estimate_name(session, person)

        session.commit()
    finally:
        session.close()
