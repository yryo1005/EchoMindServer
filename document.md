# EchoMindServer

ライフログ音声解析・QAシステムのサーバー実装(`仕様書.md`参照)．

## ディレクトリ構成

- `programs/ex001_model_benchmark/`: モデル選定のための最初のベンチマーク(疑似会話30件，無音のみ)．
  - `data.py`: JVSコーパスから疑似複数話者会話データを生成する．
  - `evaluate_vad.py`: VADモデルの比較評価(Precision/Recall/F1)．
  - `evaluate_diarization.py`: 話者分離モデルの比較評価(DER)．
  - `evaluate_asr.py`: 音声認識モデルの比較評価(CER)．
  - `evaluate_embedding.py`: 文章埋め込みモデルの比較評価(Recall@k, MRR)．
- `programs/ex002_model_benchmark/`: ex001の結果の信ぴょう性を高めるため，比較対象モデルを追加し，疑似会話データを拡充(80件，重複発話30%，加算的ノイズ付加)した再評価．
  - `data.py`: ex001と同じJVS生データを用いるが，重複発話・ノイズを追加した疑似会話を生成する．
  - `evaluate_vad.py`: ex001の2手法に加え，`pyannote/segmentation-3.0`を追加評価．
  - `evaluate_diarization.py`: pyannote 3.1のみ(`.venv_ml`で実行)．
  - `evaluate_diarization_community1.py`: `pyannote/speaker-diarization-community-1`のみ(`.venv_diarization_community`で実行，`.venv_ml`とは別環境)．
  - `evaluate_asr.py`: ex001の3モデルに加え，`reazonspeech-nemo-v2`を追加評価(サンプル数200→400件)．
  - `evaluate_embedding.py`: ex001の3モデルに加え，`multilingual-e5-base`，`pkshatech/GLuCoSE-base-ja`を追加評価(検索対象コーパスを281発話→1096発話に拡大)．
- `programs/server/`: EchoMindサーバー本体(FastAPI)．ベンチマークプログラムとは明確にディレクトリを分離している．
  - `app/main.py`: FastAPIアプリのエントリポイント．
  - `app/config.py`: モデル選定(ベンチマーク結果に基づく)やDB接続先等の設定値．
  - `app/api/upload.py`: `POST /api/upload`(音声アップロード)．
  - `app/api/chat.py`: `POST /api/chat`(QA)．
  - `app/pipeline/`: VAD・話者分離・音声単位の切り出し・ASR・文章校正・ベクトル化・話者ID統合/名前推定・パイプライン全体の統括(`orchestrator.py`)．
  - `app/db/`: SQLAlchemyモデル(`models.py`)とセッション管理(`session.py`)．
  - `app/services/gemini_client.py`: Gemini APIクライアントのラッパー(レート制限時のリトライを含む)．
  - `docker-compose.yml`: PostgreSQL+pgvectorのコンテナ定義．
  - `storage/`: アップロードされた音声・発話クリップの保存先(Git管理対象外)．
- `datasets/ex001_model_benchmark/`: ベンチマーク用データ(JVSコーパスの生音声，疑似会話データ，発話テキストのトランスクリプト)．`ex002_model_benchmark`もこのJVS生データ(`raw/`)を再利用する．Git管理対象外．
- `datasets/ex002_model_benchmark/`: ex002の疑似会話データ(重複発話・ノイズ付加)．Git管理対象外．
- `outputs/ex001_model_benchmark/`, `outputs/ex002_model_benchmark/`: 各ベンチマークの評価結果(metrics.json，比較グラフ)．Git管理対象外．
- `third_party/Haas-ASR/`: Haas-ja ASRモデルの推論コード(GitHubから手動クローン)．`haas-asr`パッケージとして`.venv_ml`にインストール済み．Git管理対象外．
- `visualize_result.ipynb`: `outputs/{EXPERIMENT}/`内の評価結果を比較グラフとして可視化するノートブック．ノートブック冒頭の`EXPERIMENT`変数で`ex001_model_benchmark`/`ex002_model_benchmark`を切り替える．
- `.orders/`: ユーザーからの作業指示の記録．
- `.reports/report_001.md`: ex001_model_benchmarkのベンチマーク結果・考察．
- `.reports/report_002.md`: ex002_model_benchmarkのベンチマーク結果・考察・モデル選定の再検討(最新)．

## プログラム間の依存関係

```text
ex001_model_benchmark/data.py (JVS生データ読み込み・疑似会話データ生成)
  └─> evaluate_vad.py / evaluate_diarization.py / evaluate_embedding.py
  └─> evaluate_asr.py (内部関数のみ再利用)

ex002_model_benchmark/data.py (ex001のJVS生データを再利用し，重複発話・ノイズを追加)
  └─> evaluate_vad.py / evaluate_diarization.py(.venv_ml) / evaluate_embedding.py
  └─> evaluate_diarization_community1.py (.venv_diarization_community，別環境)
  └─> evaluate_asr.py (ex001_model_benchmark/data.pyの内部関数を再利用)

evaluate_*.py ──> outputs/{ex001,ex002}_model_benchmark/{task}/{method}/metrics.json
                                │
                                ▼
                      visualize_result.ipynb (EXPERIMENT変数で切替) ──> outputs/.../comparison.png
                                │
                                ▼
                      .reports/report_001.md, report_002.md (モデル選定の根拠)
                                │
                                ▼
programs/server/app/main.py (FastAPIアプリ)
  ├─ api/upload.py ──(BackgroundTasks)──> pipeline/orchestrator.py
  │                                         ├─ vad.py (Silero VAD)
  │                                         ├─ diarization.py (pyannote 3.1, 話者埋め込みも取得)
  │                                         ├─ segment.py (発話単位に音声を切り出し)
  │                                         ├─ asr.py (Haas-ja)
  │                                         ├─ correction.py (Gemini APIで文章校正)
  │                                         ├─ embedding.py (ruri-large-v2)
  │                                         ├─ person_identification.py (話者ID統合・名前推定)
  │                                         └─ db/models.py へ保存(Conversation, Utterance, Person)
  └─ api/chat.py ──> pipeline/embedding.py (クエリのベクトル化)
                     ──> db(pgvectorでの類似度検索)
                     ──> services/gemini_client.py (回答生成)
```

## 外部モジュール・APIとの依存関係

- **Hugging Face Hub**: `pyannote/speaker-diarization-3.1`，`cl-nagoya/ruri-*`等のモデル取得に使用．`tokens.json`の`huggingface_hub`トークンが必要．pyannoteモデルはゲート付きのため，各モデルページでライセンスに同意しておく必要がある．
- **Gemini API**: ベクトル検索ベンチマークの質問文生成，およびサーバー実装後のQA回答生成に使用．`tokens.json`の`gemini`キーが必要．無料枠のレート制限(1分あたり15リクエスト程度)に注意する．
- **Haas-ASR** (`third_party/Haas-ASR/`): third-intelligence社のGitHubリポジトリをクローンし，`uv pip install ./third_party/Haas-ASR`でローカルインストールしている．NeMo 2.7, Python 3.11以上が必要．
- **pyannote/speaker-diarization-community-1**: `pyannote.audio>=4.0`が必要であり，`.venv_ml`(`pyannote.audio==3.3.2`, Haas-ja等が依存)とは非互換．別の仮想環境`.venv_diarization_community`を用意して評価する．

## Python環境の構築方法

```bash
uv venv .venv_ml --python 3.11
uv pip install --python .venv_ml -r requirements_ml.txt
# Haas-ASRはGitHubからのコード取得を伴うため，別途third_party/にクローンした上で
# ローカルインストールする(pip install git+https://... は許可されない環境がある)
git clone https://github.com/third-intelligence/Haas-ASR.git third_party/Haas-ASR
uv pip install --python .venv_ml ./third_party/Haas-ASR
```

Jupyterカーネルとして使用する場合:

```bash
.venv_ml/bin/python -m ipykernel install --user --name venv_ml --display-name ".venv_ml"
```

`pyannote/speaker-diarization-community-1`の評価には別環境が必要:

```bash
uv venv .venv_diarization_community --python 3.11
uv pip install --python .venv_diarization_community "pyannote.audio" torch torchaudio soundfile numpy pyannote.metrics tqdm
```

## プログラムの実行方法

```bash
# 疑似ベンチマークデータの生成(ex001, ex002それぞれで実行する)
.venv_ml/bin/python programs/ex001_model_benchmark/data.py
.venv_ml/bin/python programs/ex002_model_benchmark/data.py

# ex002の各タスクのベンチマーク実行(プロジェクトルートから実行する)
.venv_ml/bin/python programs/ex002_model_benchmark/evaluate_vad.py
.venv_ml/bin/python programs/ex002_model_benchmark/evaluate_diarization.py
.venv_diarization_community/bin/python programs/ex002_model_benchmark/evaluate_diarization_community1.py
.venv_ml/bin/python programs/ex002_model_benchmark/evaluate_asr.py
.venv_ml/bin/python programs/ex002_model_benchmark/evaluate_embedding.py

# 結果の可視化(ノートブック冒頭のEXPERIMENT変数で対象実験を切り替える)
.venv_ml/bin/jupyter nbconvert --to notebook --execute --inplace visualize_result.ipynb
```

### サーバー本体(programs/server/)の起動方法

```bash
# PostgreSQL+pgvectorコンテナの起動(初回のみ．以降は自動的に永続化される)
cd programs/server && docker compose up -d && cd ../..

# サーバー起動(初回起動時にpgvector拡張の有効化・テーブル作成を自動で行う)
cd programs/server && ../../.venv_ml/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

動作確認:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/upload -F "file=@/path/to/audio.wav"
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"user_id": "user01", "query": "明日のMTGは何時から？"}'
```

テスト:

```bash
.venv_ml/bin/python -m pytest tests/test_server.py -v
```

## 実験結果・文書の保存場所

- 評価結果の数値: `outputs/{ex001,ex002}_model_benchmark/{vad,diarization,asr,embedding}/{手法名}/metrics.json`
- 比較グラフ: `outputs/{ex001,ex002}_model_benchmark/{vad,diarization,asr,embedding}/comparison.png`
- レポート: `.reports/report_001.md`(初回)，`.reports/report_002.md`(拡充版，最新)

## 必要なAPIキー・設定ファイル

`tokens.json`(プロジェクトルート，Git管理対象外)に以下のキーを含む必要がある．

```json
{
  "huggingface_hub": "...",
  "gemini": "..."
}
```

サーバー本体のDB接続先は`programs/server/app/config.py`の`DATABASE_URL`にハードコードされている(docker-composeのデフォルト値と一致)．本番運用時は環境変数化を検討すること．

## Git管理上の注意事項

- `tokens.json`，`.venv_ml/`，`.venv_diarization_community/`，`datasets/`，`outputs/`，`third_party/`，`programs/server/storage/`はGit管理対象外(`.gitignore`参照)．
- `third_party/Haas-ASR/`はGitHubから手動クローンした外部リポジトリであり，本プロジェクトのコードとしては管理しない．
- PostgreSQLのデータ(docker volume `server_pgdata`)もGit管理対象外．コンテナを削除するとDBの内容も失われるため注意する．
