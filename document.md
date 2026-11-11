# EchoMindServer

ライフログ音声解析・QAシステムのサーバー実装(`仕様書.md`参照)．

サーバーの起動方法・Cloudflare Tunnelでの公開方法は[programs/server/README.md](programs/server/README.md)にまとめている．本ファイルはプロジェクト全体の構成・依存関係・実験の経緯を記録する．

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
  - `app/api/auth.py`: `POST /api/auth/register`(アカウント登録)，`POST /api/auth/login`(ログイン)，`GET /api/auth/me`(現在のユーザー情報)．
  - `app/auth.py`: パスワードハッシュ化(bcrypt)，JWTアクセストークンの発行・検証，`get_current_user`依存関数．
  - `app/api/upload.py`: `POST /api/upload`(音声アップロード，認証必須)．録音開始時刻はクライアントが報告する`recorded_started_at`(ISO8601)を用い，サーバーの受信時刻は使用しない．アップロード音声のSHA256ハッシュによる重複アップロード防止(`UploadRecord`)を行う．処理が例外で失敗した場合や，サーバー異常終了等で"processing"のまま長時間更新されない場合は再試行を許可する．
  - `app/timeutil.py`: 日時のタイムゾーン変換ユーティリティ．DBのdatetime列はタイムゾーン情報を持たない(naive)が「常にUTC」として扱う規約を集約し，クライアント入力の解析・APIレスポンスでのUTC明示・日本時間(JST)表示への変換を提供する．
  - `app/api/chat.py`: `POST /api/chat`(QA，認証必須．自分のアカウントのデータのみ検索対象とする)．Gemini APIへ渡す会話記録のタイムスタンプは日本時間(JST)に変換し，現在の日本時間も明示する(UTCのまま渡すと「何時から？」等の回答が9時間ずれるため)．
  - `app/api/browse.py`: `GET /api/persons`，`PUT /api/persons/{id}/name`(名前の手動設定)，`GET /api/conversations`，`GET /api/conversations/{id}`(ブラウザフロントエンド用の会話・発言閲覧API．いずれも認証必須)．
  - `app/api/audio.py`: `GET /api/audio/{utterance_id}`(発言の音声クリップ配信，認証必須．自分のアカウントの発言以外は404)．
  - `app/pipeline/`: VAD・話者分離・音声単位の切り出し・ASR・文章校正・ベクトル化・話者ID統合/名前推定・パイプライン全体の統括(`orchestrator.py`)．話者ID統合(`resolve_person`)はアカウント(user_id)内でのみ照合する．発話クリップはAAC(.m4a)で保存し(`segment.py`)，ASR(`asr.py`)はAAC非対応のlibsndfile制約を避けるため切り出し前の波形を直接受け取る．
  - `app/db/`: SQLAlchemyモデル(`models.py`: User, Person, Conversation, Utterance)とセッション管理(`session.py`)．
  - `app/services/gemini_client.py`: Gemini APIクライアントのラッパー．1分あたりのレート制限・一時的なサーバーエラーは同一モデルで指数バックオフリトライし，1日あたりのリクエスト数上限に達した場合は候補モデル(`_MODEL_CANDIDATES`)へ自動的に切り替える．
  - `docker-compose.yml`: PostgreSQL+pgvectorおよびCloudflare Tunnel(`cloudflared`)のコンテナ定義．
  - `.env.example`: Cloudflare Tunnelのトークン(`CLOUDFLARE_TUNNEL_TOKEN`)を設定するための環境変数ファイルのテンプレート．実際の`.env`はGit管理対象外．
  - `scripts/assign_existing_data_to_user.py`: アカウント機能追加前に作成された既存データ(user_id未設定のConversation/Person)を，指定したメールアドレスのアカウントに帰属づけ，そのアカウントをadminロールにする一度限りの移行スクリプト．
  - `static/`: ブラウザ用フロントエンド(ビルドツールを使わないプレーンなHTML/JS/CSS．`app.main`がルートパスに静的配信する)．ログイン・アカウント登録画面，質問タブ，会話閲覧タブ，話者の名前設定タブを持つ．`index.html`，`app.js`，`style.css`．アクセストークンはブラウザの`localStorage`に保存する．
  - `storage/`: アップロードされた音声・発話クリップの保存先(Git管理対象外)．
- `programs/ex003_server_evaluation/`: `programs/server/`のパイプライン自体(モデル選定ではなく)の精度検証．話者ID統合と名前推定を対象とする．
  - `data_speaker_id.py`: 同一話者が複数の別々の会話(アップロード)に跨って登場する疑似データ(15セッション，話者プール10名)を生成する．
  - `evaluate_speaker_id.py`: 生成したセッションを実際のサーバーパイプライン(評価用DB`echomind_eval`を使用)に通し，人物ID統合の純度を評価する．
  - `data_name_estimation.py`: 名前の手がかり(自己紹介・呼びかけ)を含む疑似会話テキストをGemini APIで生成する(TTSが利用できないため，テキストレベルの検証に限定)．
  - `evaluate_name_estimation.py`: サーバーが実際に使用する名前推定関数(`estimate_name_from_context`)の精度を評価する．
  - `visualize_result.ipynb`: このディレクトリ専用の可視化ノートブック(ex001/ex002のモデル比較とは評価軸が異なるため，プロジェクトルートのノートブックとは別に用意している)．
- `datasets/ex001_model_benchmark/`: ベンチマーク用データ(JVSコーパスの生音声，疑似会話データ，発話テキストのトランスクリプト)．`ex002_model_benchmark`，`ex003_server_evaluation`もこのJVS生データ(`raw/`)を再利用する．Git管理対象外．
- `datasets/ex002_model_benchmark/`: ex002の疑似会話データ(重複発話・ノイズ付加)．Git管理対象外．
- `datasets/ex003_server_evaluation/`: ex003の疑似複数セッションデータ，名前推定テストケース．Git管理対象外．
- `outputs/ex001_model_benchmark/`, `outputs/ex002_model_benchmark/`, `outputs/ex003_server_evaluation/`: 各検証の評価結果(metrics.json，比較グラフ)．Git管理対象外．
- `third_party/Haas-ASR/`: Haas-ja ASRモデルの推論コード(GitHubから手動クローン)．`haas-asr`パッケージとして`.venv_ml`にインストール済み．Git管理対象外．
- `visualize_result.ipynb`: `outputs/{EXPERIMENT}/`内の評価結果を比較グラフとして可視化するノートブック(ex001/ex002用)．ノートブック冒頭の`EXPERIMENT`変数で`ex001_model_benchmark`/`ex002_model_benchmark`を切り替える．
- `.orders/`: ユーザーからの作業指示の記録．
- `.reports/report_001.md`: ex001_model_benchmarkのベンチマーク結果・考察．
- `.reports/report_002.md`: ex002_model_benchmarkのベンチマーク結果・考察・モデル選定の再検討．
- `.reports/report_003.md`: サーバー実装(programs/server/)の内容・動作確認結果．
- `.reports/report_004.md`: ex003_server_evaluationの精度検証結果(話者ID統合・名前推定，最新)．

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
  │                                         ├─ correction.py (Gemini APIで文章校正．会話内の全発話をまとめて1回のAPI呼び出しで処理)
  │                                         ├─ embedding.py (ruri-large-v2)
  │                                         ├─ person_identification.py (話者ID統合・名前推定)
  │                                         └─ db/models.py へ保存(Conversation, Utterance, Person)
  └─ api/chat.py ──> pipeline/embedding.py (クエリのベクトル化)
                     ──> db(pgvectorでの類似度検索)
                     ──> services/gemini_client.py (回答生成)
                                │
                                ▼
programs/ex003_server_evaluation/ (パイプライン自体の精度検証)
  ├─ data_speaker_id.py ──> evaluate_speaker_id.py
  │       (orchestrator.process_uploaded_audioを評価用DB"echomind_eval"に向けて直接呼び出す)
  └─ data_name_estimation.py ──> evaluate_name_estimation.py
          (person_identification.estimate_name_from_contextを直接呼び出す)
                                │
                                ▼
                      .reports/report_004.md
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

# アカウント登録・ログイン(以降のAPIはアクセストークンが必要)
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/api/upload -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/recording.m4a" \
  -F "recorded_started_at=2026-11-11T09:00:00Z" \
  -F "client_file_id=任意のクライアント発行ID(省略可)"
curl -X POST http://localhost:8000/api/chat -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "明日のMTGは何時から？"}'
```

既存のデバッグ用データ(アカウント機能追加前に蓄積したデータ)をいずれかのアカウントに帰属づける場合(一度だけ実行する):

```bash
.venv_ml/bin/python programs/server/scripts/assign_existing_data_to_user.py --email you@example.com
```

ブラウザ用フロントエンド: サーバー起動後，`http://localhost:8000/`をブラウザで開くと，ログイン・アカウント登録画面が表示される．ログイン後，質問(QA)タブ・過去の会話を聞くタブ・話者の名前を設定タブが利用できる．

テスト:

```bash
.venv_ml/bin/python -m pytest tests/test_server.py -v
```

### サーバーパイプラインの精度検証(ex003_server_evaluation)

```bash
# 評価用DBの作成(本番用"echomind"とは別のDB．初回のみ)
docker exec <postgresコンテナ名> psql -U echomind -d echomind -c "CREATE DATABASE echomind_eval"

# 話者ID統合の精度検証
.venv_ml/bin/python programs/ex003_server_evaluation/data_speaker_id.py
.venv_ml/bin/python programs/ex003_server_evaluation/evaluate_speaker_id.py

# 名前推定の精度検証(Gemini APIで疑似会話テキストを生成してから評価する)
.venv_ml/bin/python programs/ex003_server_evaluation/data_name_estimation.py
.venv_ml/bin/python programs/ex003_server_evaluation/evaluate_name_estimation.py

# 結果の可視化
.venv_ml/bin/jupyter nbconvert --to notebook --execute --inplace programs/ex003_server_evaluation/visualize_result.ipynb
```

## 実験結果・文書の保存場所

- 評価結果の数値: `outputs/{ex001,ex002}_model_benchmark/{vad,diarization,asr,embedding}/{手法名}/metrics.json`，`outputs/ex003_server_evaluation/{speaker_id,name_estimation}/metrics.json`
- 比較グラフ: `outputs/{ex001,ex002}_model_benchmark/{vad,diarization,asr,embedding}/comparison.png`，`outputs/ex003_server_evaluation/{speaker_id,name_estimation}/comparison.png`
- レポート: `.reports/report_001.md`(モデル選定・初回)，`report_002.md`(モデル選定・拡充版)，`report_003.md`(サーバー実装)，`report_004.md`(パイプライン精度検証)，`report_005.md`(ブラウザフロントエンド・アカウント機能)，`report_006.md`(録音タイムスタンプ・軽量音声形式・重複防止・Cloudflare公開)，`report_007.md`(失敗時の永久ブロック・競合・タイムゾーンの修正，最新)

## 必要なAPIキー・設定ファイル

`tokens.json`(プロジェクトルート，Git管理対象外)に以下のキーを含む必要がある．

```json
{
  "huggingface_hub": "...",
  "gemini": "..."
}
```

`jwt_secret`(JWTアクセストークンの署名鍵)は，サーバー初回起動時に`app.config.get_jwt_secret()`が自動生成し，`tokens.json`に書き込んで永続化する．手動で用意する必要はない．

サーバー本体のDB接続先は`programs/server/app/config.py`の`DATABASE_URL`にハードコードされている(docker-composeのデフォルト値と一致)．本番運用時は環境変数化を検討すること．

## Git管理上の注意事項

- `tokens.json`，`.venv_ml/`，`.venv_diarization_community/`，`datasets/`，`outputs/`，`third_party/`，`programs/server/storage/`はGit管理対象外(`.gitignore`参照)．
- `third_party/Haas-ASR/`はGitHubから手動クローンした外部リポジトリであり，本プロジェクトのコードとしては管理しない．
- PostgreSQLのデータ(docker volume `server_pgdata`)もGit管理対象外．コンテナを削除するとDBの内容も失われるため注意する．
