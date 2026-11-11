# EchoMindServer 改善レポート(録音タイムスタンプ・軽量音声形式・重複防止・Cloudflare公開)

## 1. 録音開始時刻をクライアント報告値に変更

### 1.1 問題

これまでサーバーはファイルを受信した時刻(`datetime.utcnow()`)を発言のタイムスタンプの基準としていた．ネットワーク遅延・再送・アップロードの遅延等により，実際の録音タイミングとサーバーの受信タイミングはずれるため，これは誤ったタイムスタンプを記録する可能性があった．

### 1.2 対応

`POST /api/upload`に，クライアントが報告する録音開始時刻を必須のフォームフィールド`recorded_started_at`(ISO8601形式)として追加した．サーバーはこの値のみを発言のタイムスタンプ算出の基準とし，受信時刻は一切使用しない．

ファイル名から開始・終了時刻を解析する方式も検討したが，フォームフィールドとして明示的に送る方式を採用した(ファイル名のエンコード・デコードの実装がクライアント側・サーバー側の両方で必要になり，誤った形式への対応等で複雑になるため)．iPhoneアプリ側では，録音開始時の`Date()`をISO8601文字列に変換して送信すればよい．

```
POST /api/upload
Content-Type: multipart/form-data

file: (音声データ)
recorded_started_at: "2026-11-11T09:00:00Z"
client_file_id: "任意のクライアント発行ID(省略可，重複検出の補助に使用)"
```

## 2. 音声の保存形式を軽量なAACに変更

### 2.1 問題

サーバーは拡張子に関わらず全てのアップロード音声・発話クリップを`.wav`として保存していた．クライアントがAACで送信する前提であれば，サーバー側でも非圧縮のwavで保存する必要はなく，ストレージを不必要に消費していた．

### 2.2 対応

- アップロードされたファイルは，元のファイル名の拡張子をそのまま保存する(`.m4a`/`.aac`等．不明な場合は`.m4a`を既定値とする)．サーバーが独自に`.wav`へ付け替えることはしない．
- 話者分離後に切り出す発話クリップは，非圧縮wavではなくAAC(.m4a, `ffmpeg`による圧縮)で保存するよう変更した(`app/pipeline/segment.py`)．実測で非圧縮wav比およそ3分の1程度のサイズになることを確認した．
- 音声認識(Haas-ja)は内部でlibsndfileを使用しており，AACを直接デコードできないため，保存用のAACファイルを再度読み込むのではなく，分割前にデコード済みの波形をそのままASRに渡すよう`app/pipeline/asr.py`・`app/pipeline/segment.py`・`app/pipeline/orchestrator.py`を変更した(音質の劣化や読み込みエラーを避けるため)．
- `GET /api/audio/{utterance_id}`は，ファイル拡張子に応じて`Content-Type`(`audio/mp4`または`audio/wav`)を自動的に切り替える．

## 3. アップロードの重複処理防止

### 3.1 問題

アップロードへの応答がクライアントに届かず失われた場合，クライアントが同じ音声を再送すると，サーバーは同じ内容を重複して処理してしまう可能性があった．

### 3.2 対応

アップロードされた音声データのSHA256ハッシュを用いた冪等性チェックを実装した(`UploadRecord`テーブル，`app/api/upload.py`)．

- アカウント内で同じSHA256ハッシュのアップロードが既に存在する場合，サーバーは新たな処理を行わず，`{"status": "duplicate", "upload_record_id": ..., "processing_status": ..., "conversation_id": ...}`を返す．処理中であればその旨，完了していればその会話IDを返す．
- 初回のアップロードは`UploadRecord(status="processing")`として記録し，バックグラウンド処理が完了すると`"completed"`(会話IDを記録)または`"rejected"`(VADで発話が検出されなかった，または話者が1名のみで「会話」とみなされなかった場合)に更新される．
- クライアントが発行する`client_file_id`も併せて記録しているが，実際の重複判定はSHA256ハッシュのみで行う(クライアントIDの実装ミスや再利用があっても，内容が同じであれば確実に重複として検出できるようにするため)．

## 4. 動作確認

- `recorded_started_at`を指定せずにアップロードすると422エラーになることを確認した．
- `recorded_started_at="2026-03-01T08:30:00"`を指定してアップロードしたところ，会話の`started_at`がサーバーの受信時刻(2026年11月)ではなく指定した時刻(2026年3月1日)として記録されることを確認した．
- 同一ファイルを同じ`client_file_id`で再送したところ，`"status": "duplicate"`が返り，処理が重複して実行されないことを確認した．
- アップロードされたファイル・発話クリップがAAC(.m4a, AAC-LC)として保存され，`GET /api/audio/{utterance_id}`で正しく再生可能な状態で配信されることを確認した．文字起こし結果も問題なく生成されることを確認した．

テスト: `tests/test_server.py`に，録音開始時刻の解析(`_parse_recorded_started_at`)・拡張子推定(`_guess_extension`)のユニットテストを追加し，全13件が合格することを確認した．

## 5. Cloudflare Tunnelによる公開

既に所有しているドメイン`stargazyguys.com`(Cloudflareで管理)のサブドメインを用いて，EchoMindサーバーをインターネットに公開するためのセットアップを行った．

### 5.1 リポジトリ側で用意したもの

- `programs/server/docker-compose.yml`に`cloudflared`サービスを追加した．`cloudflare/cloudflared`公式イメージを使い，`network_mode: host`でホストのlocalhost:8000(uvicornが動くポート)に到達できるようにしている．
- `programs/server/.env.example`: Cloudflare Tunnelのトークンを設定するための環境変数ファイルのテンプレート(実際の`.env`はGit管理対象外)．

### 5.2 ユーザー側で実施が必要な操作(Cloudflare)

AIエディタはユーザーのCloudflareアカウントを操作できないため，以下はユーザー自身がCloudflareダッシュボードで行う必要がある．

1. **Cloudflare Zero Trustダッシュボード**(https://one.dash.cloudflare.com/ )にログインする．
2. 左メニューの「Networks」→「Tunnels」を開き，「Create a tunnel」をクリックする．
3. コネクタの種類として「Cloudflared」を選択し，トンネル名を入力する(例: `echomind`)．
4. 次の画面で表示される「Install and run a connector」の手順の中に，トンネルのトークンが含まれている(`cloudflared service install <トークン>`のような形，または環境変数`TUNNEL_TOKEN`として表示される)．このトークンをコピーする．
5. 自宅サーバー上で，`programs/server/.env.example`を`programs/server/.env`としてコピーし，`CLOUDFLARE_TUNNEL_TOKEN`に手順4のトークンを設定する．
6. ダッシュボードに戻り，作成したトンネルの「Public Hostname」タブで「Add a public hostname」をクリックする．
   - **Subdomain**: 任意のサブドメイン名(例: `echomind`)
   - **Domain**: `stargazyguys.com`を選択する
   - **Path**: 空のまま(ルート全体を公開する場合)
   - **Service**: Type=`HTTP`，URL=`localhost:8000`
   - 保存すると，Cloudflareが`stargazyguys.com`のDNSゾーンに，このサブドメインから当該トンネルへのCNAMEレコードを自動的に作成する(ユーザーが手動でDNSレコードを追加する必要はない)．
7. 自宅サーバーで以下を実行してコンテナを起動する:
   ```bash
   cd programs/server
   docker compose up -d
   ```
8. `https://echomind.stargazyguys.com/health`(手順6で設定したサブドメインに置き換える)にアクセスし，`{"status":"ok"}`が返ることを確認する．

### 5.3 注意事項

- トンネル経由で公開した場合でも，アプリケーション層の認証(メールアドレス+パスワードでのログイン，JWT)はそのまま有効であり，追加の保護が必要な場合はCloudflare Access(Zero Trustのアクセスポリシー)の設定も検討できる．
- `docker-compose.yml`の`db`サービスはポート5432をホストに公開しているが，これはCloudflare Tunnel経由では公開されない(Tunnelはingressで指定したサービス，ここでは`localhost:8000`のみを公開する)．PostgreSQLを外部に公開する設定にはなっていない．
- 本タスクではCloudflareダッシュボードでの実際の操作・動作確認は行っていない(AIエディタの権限・環境の制約のため)．上記手順通りに進めた上で，`/health`での動作確認をユーザー側で実施してほしい．
