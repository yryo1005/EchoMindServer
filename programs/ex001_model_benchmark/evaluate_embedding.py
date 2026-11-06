"""文章埋め込み(ベクトル検索)モデルのベンチマーク評価スクリプト．

疑似会話(data.pyで生成)の各発話テキストをコーパスとしてベクトル化し，
発話内容に基づく質問に対して正解発話を検索できるかをRecall@k・MRRで評価する．
質問はGemini APIを用いて各発話テキストから自動生成する．
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from google import genai
from google.genai import errors as genai_errors
from sentence_transformers import SentenceTransformer
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential
from tqdm import tqdm

from data import SYNTHETIC_DIR

OUTPUT_DIR = Path("outputs/ex001_model_benchmark/embedding")
TOP_K_LIST = [1, 3, 5]


def _load_gemini_api_key() -> str:
    """tokens.jsonからGemini APIキーを読み込む関数．

    引数:
        なし
    戻り値:
        api_key (str): Gemini APIキー
    """
    with open("tokens.json", encoding="utf-8") as f:
        return json.load(f)["gemini"]


@retry(
    retry=retry_if_exception_type((genai_errors.ServerError, genai_errors.ClientError)),
    wait=wait_random_exponential(multiplier=2, max=60),
    stop=stop_after_attempt(8),
)
def _generate_question(client: genai.Client, text: str) -> str:
    """1件の発話テキストから質問文をGemini APIで生成する関数(一時的なエラーはリトライする)．

    引数:
        client (genai.Client): Gemini APIクライアント
        text (str): 質問の元となる発話テキスト
    戻り値:
        question (str): 生成された質問文
    """
    prompt = (
        "次の発言内容だけから答えられる，具体的な一問一答形式の短い日本語の質問を1つだけ作成してください．"
        "質問文のみを出力し，他の説明は不要です．\n\n"
        f"発言: {text}"
    )
    response = client.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt)
    return response.text.strip()


def _collect_corpus_and_queries(client: genai.Client) -> tuple[list[str], list[tuple[str, int]]]:
    """全会話の発話テキストをコーパス化し，各発話に対応する質問を生成する関数．

    既に質問生成キャッシュ(queries_cache.json)が存在する場合はこれを再利用し，
    Gemini APIの呼び出し(レート制限のため時間がかかる)を省略する．

    引数:
        client (genai.Client): Gemini APIクライアント
    戻り値:
        corpus (list[str]): 発話テキストの一覧(検索対象)
        queries (list[tuple[str, int]]): (質問文, 正解となるcorpus中のインデックス)の一覧
    """
    cache_path = OUTPUT_DIR / "queries_cache.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached["corpus"], [tuple(q) for q in cached["queries"]]

    corpus: list[str] = []
    for metadata_path in sorted(SYNTHETIC_DIR.glob("conv_*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for utterance in metadata["utterances"]:
            corpus.append(utterance["text"])

    # Gemini API無料枠のレート制限(15 requests/分)を超えないよう，呼び出し間隔を空ける
    seconds_per_request = 4.5
    queries: list[tuple[str, int]] = []
    for idx, text in enumerate(tqdm(corpus, desc="generate_queries", leave=False)):
        question = _generate_question(client, text)
        queries.append((question, idx))
        time.sleep(seconds_per_request)

    return corpus, queries


def evaluate_method(method_name: str, model_id: str, corpus: list[str], queries: list[tuple[str, int]]) -> None:
    """指定した埋め込みモデルで検索精度を評価し，結果を保存する関数．

    引数:
        method_name (str): 結果保存時に使う手法名
        model_id (str): sentence-transformersのモデルID
        corpus (list[str]): 発話テキストの一覧(検索対象)
        queries (list[tuple[str, int]]): (質問文, 正解となるcorpus中のインデックス)の一覧
    戻り値:
        なし
    """
    model = SentenceTransformer(model_id)
    is_ruri = "ruri" in model_id

    corpus_prefixed = [f"文章: {t}" for t in corpus] if is_ruri else corpus
    query_prefixed = [f"クエリ: {q}" for q, _ in queries] if is_ruri else [q for q, _ in queries]

    corpus_embeddings = model.encode(corpus_prefixed, normalize_embeddings=True)
    query_embeddings = model.encode(query_prefixed, normalize_embeddings=True)

    similarities = query_embeddings @ corpus_embeddings.T  # shape=(n_queries, n_corpus)
    ranked_indices = np.argsort(-similarities, axis=1)

    recall_at_k = {k: 0 for k in TOP_K_LIST}
    reciprocal_ranks = []
    for query_idx, (_, correct_idx) in enumerate(queries):
        rank_positions = np.where(ranked_indices[query_idx] == correct_idx)[0]
        rank = int(rank_positions[0]) + 1 if len(rank_positions) > 0 else len(corpus) + 1
        reciprocal_ranks.append(1.0 / rank)
        for k in TOP_K_LIST:
            if rank <= k:
                recall_at_k[k] += 1

    n_queries = len(queries)
    metrics = {
        "mrr": float(np.mean(reciprocal_ranks)),
        **{f"recall@{k}": count / n_queries for k, count in recall_at_k.items()},
    }

    target_dir = OUTPUT_DIR / method_name
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(method_name, metrics)


if __name__ == "__main__":
    gemini_client = genai.Client(api_key=_load_gemini_api_key())
    corpus, queries = _collect_corpus_and_queries(gemini_client)

    queries_cache_path = OUTPUT_DIR / "queries_cache.json"
    queries_cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queries_cache_path, "w", encoding="utf-8") as f:
        json.dump({"corpus": corpus, "queries": queries}, f, ensure_ascii=False, indent=2)

    for method_name, model_id in [
        ("ruri_base", "cl-nagoya/ruri-base"),
        ("ruri_large_v2", "cl-nagoya/ruri-large-v2"),
        ("multilingual_e5_large", "intfloat/multilingual-e5-large"),
    ]:
        evaluate_method(method_name, model_id, corpus, queries)
