"""文章埋め込み(ベクトル検索)モデルのベンチマーク評価スクリプト(ex002: 拡充版)．

ex001からの変更点:
    - 比較対象に`multilingual-e5-base`，`pkshatech/GLuCoSE-base-ja`を追加した．
    - 疑似会話数の増加(30件→80件)に伴い，コーパス・質問数も増えている．
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
from google import genai
from google.genai import errors as genai_errors
from sentence_transformers import SentenceTransformer
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential
from tqdm import tqdm

from data import SYNTHETIC_DIR

OUTPUT_DIR = Path("outputs/ex002_model_benchmark/embedding")
TOP_K_LIST = [1, 3, 5]
N_QUERY_SAMPLES = 400  # コーパス全体(検索対象)は維持し，質問生成対象のみサンプリングする(API呼び出し削減のため)
SEED = 0


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
    response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
    return response.text.strip()


def _collect_corpus_and_queries(client: genai.Client) -> tuple[list[str], list[tuple[str, int]]]:
    """全会話の発話テキストをコーパス化し，各発話に対応する質問を生成する関数．

    既に質問生成キャッシュ(queries_cache.json)が存在する場合はこれを再利用する．

    引数:
        client (genai.Client): Gemini APIクライアント
    戻り値:
        corpus (list[str]): 発話テキストの一覧(検索対象)
        queries (list[tuple[str, int]]): (質問文, 正解となるcorpus中のインデックス)の一覧
    """
    cache_path = OUTPUT_DIR / "queries_cache.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    corpus: list[str] = []
    for metadata_path in sorted(SYNTHETIC_DIR.glob("conv_*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for utterance in metadata["utterances"]:
            corpus.append(utterance["text"])

    rng = random.Random(SEED)
    sample_indices = rng.sample(range(len(corpus)), k=min(N_QUERY_SAMPLES, len(corpus)))

    # 途中でAPIのレート制限・クォータに達した場合に備え，既に生成済みの質問はキャッシュから再利用し，
    # 1件生成するたびにキャッシュへ追記保存する(途中終了しても進捗が失われないようにする)
    queries: list[tuple[str, int]] = []
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["corpus"] == corpus:
            queries = [tuple(q) for q in cached["queries"]]
    done_indices = {idx for _, idx in queries}

    def _save_cache() -> None:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"corpus": corpus, "queries": queries}, f, ensure_ascii=False, indent=2)

    for idx in tqdm(sample_indices, desc="generate_queries", leave=False):
        if idx in done_indices:
            continue
        question = _generate_question(client, corpus[idx])
        queries.append((question, idx))
        _save_cache()
        time.sleep(4.5)

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
    model = SentenceTransformer(model_id, trust_remote_code=True)
    is_ruri = "ruri" in model_id
    is_e5 = "e5" in model_id

    if is_ruri:
        corpus_prefixed = [f"文章: {t}" for t in corpus]
        query_prefixed = [f"クエリ: {q}" for q, _ in queries]
    elif is_e5:
        corpus_prefixed = [f"passage: {t}" for t in corpus]
        query_prefixed = [f"query: {q}" for q, _ in queries]
    else:
        corpus_prefixed = corpus
        query_prefixed = [q for q, _ in queries]

    corpus_embeddings = model.encode(corpus_prefixed, normalize_embeddings=True)
    query_embeddings = model.encode(query_prefixed, normalize_embeddings=True)

    similarities = query_embeddings @ corpus_embeddings.T
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

    for method_name, model_id in [
        ("ruri_base", "cl-nagoya/ruri-base"),
        ("ruri_large_v2", "cl-nagoya/ruri-large-v2"),
        ("multilingual_e5_large", "intfloat/multilingual-e5-large"),
        ("multilingual_e5_base", "intfloat/multilingual-e5-base"),
        ("glucose_base_ja", "pkshatech/GLuCoSE-base-ja"),
    ]:
        evaluate_method(method_name, model_id, corpus, queries)
