# EchoMind Server

ライフログ音声解析・QAシステムのサーバー本体．設計の詳細は[document.md](../../document.md)，
モデル選定・精度検証・各機能追加の経緯は`.reports/report_001.md`〜`report_006.md`を参照．

## 前提

- `.venv_ml`(プロジェクトルートに作成済みのPython仮想環境)
- Docker / Docker Compose(PostgreSQL+pgvector，Cloudflare Tunnelのコンテナ用)
- プロジェクトルートの`tokens.json`に`huggingface_hub`・`gemini`キーが設定されていること

## 1. データベースの起動

```bash
cd programs/server
docker compose up -d db
```

(Cloudflare Tunnelも含めて両方のコンテナを一度に起動したい場合は，個別に`db`/`cloudflared`を指定せず`docker compose up -d`のみでよい．)

初回のみ，既存のデバッグ用データを特定のアカウントに帰属づける場合は[既存データの移行](#既存データの移行)を参照．

## 2. サーバー(API)の起動

```bash
cd programs/server
../../.venv_ml/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

初回起動時にpgvector拡張の有効化とテーブル作成が自動で行われる．ログアウトしてもサーバーを動かし続けたい場合は，`nohup`や`tmux`，あるいは下記のsystemdサービス化を行うこと．

動作確認:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

ブラウザからは`http://localhost:8000/`(公開後は`https://<サブドメイン>.<ドメイン>/`)でアクセスする．ログイン・アカウント登録画面が表示される．

### systemdサービス化の例(自宅サーバーで常時稼働させる場合)

```ini
# /etc/systemd/system/echomind-server.service
[Unit]
Description=EchoMind Server
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=/home/<ユーザー名>/workspace/EchoMindServer/programs/server
ExecStart=/home/<ユーザー名>/workspace/EchoMindServer/.venv_ml/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now echomind-server
```

## 3. インターネットへの公開(Cloudflare Tunnel)

既に所有しているドメイン(Cloudflareで管理)のサブドメインで公開する．手順の全体像は`.reports/report_006.md`の「5. Cloudflare Tunnelによる公開」を参照．概要:

1. Cloudflare Zero Trustダッシュボード(https://one.dash.cloudflare.com/ )→「Networks」→「Tunnels」で新しいトンネルを作成し，発行されたトークンを`programs/server/.env`の`CLOUDFLARE_TUNNEL_TOKEN`に設定する(`.env.example`を参考にする．`.env`はGit管理対象外)．
2. 作成したトンネルの「Routes」(または「Public Hostname」)で，サブドメイン・ドメインと転送先`http://localhost:8000`を登録する(保存すると該当ドメインのDNSレコードが自動的に作成される)．
3. Cloudflare Tunnelのコンテナを起動する:

```bash
cd programs/server
docker compose up -d cloudflared
```

4. トンネルのステータスがダッシュボード上で「Healthy」になっていることを確認する．
5. `../../.venv_ml/bin/uvicorn ...`(手順2)でサーバー本体を起動しておく(トンネルは`localhost:8000`に転送するだけであり，アプリ自体は別途起動が必要)．
6. `https://<サブドメイン>.<ドメイン>/health`にアクセスして`{"status":"ok"}`が返ることを確認する．

### 起動順序の注意

Cloudflare Tunnel(`cloudflared`)は転送先(`localhost:8000`)に何か起動していなくても正常に接続できてしまう(トンネル自体は`Healthy`と表示される)．`curl http://localhost:8000/health`がタイムアウトせず応答することを必ず確認してから公開URLへアクセスすること．

## 既存データの移行

アカウント機能の追加前に作成したデバッグ用データ(特定のアカウントに紐付いていない会話・人物)がある場合，ブラウザでアカウントを1つ登録した後に以下を実行し，そのアカウントに帰属づける(1回のみ実行する):

```bash
../../.venv_ml/bin/python scripts/assign_existing_data_to_user.py --email <登録したメールアドレス>
```

実行したアカウントは`admin`ロールになる．

## テスト

```bash
# プロジェクトルートから実行する
.venv_ml/bin/python -m pytest tests/test_server.py -v
```

## 停止

```bash
cd programs/server
docker compose down   # DB・Cloudflare Tunnelのコンテナを停止する(データは保持される)
```

uvicornプロセスは`Ctrl+C`，またはsystemd管理の場合は`sudo systemctl stop echomind-server`で停止する．
