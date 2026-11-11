# EchoMindServer 不具合修正レポート(失敗時の永久ブロック・競合・タイムゾーン)

外部レビューで指摘された3件の不具合を修正した．

## A. 処理失敗時にアップロードが永久にブロックされる問題

### 問題

`process_uploaded_audio`内で例外(ASR・Gemini APIのエラー，サーバーの異常終了等)が発生すると，`UploadRecord.status`が`"processing"`のまま更新されずに残る．クライアントが同じ音声を再送すると，冪等性チェックが`"processing"`を既存の処理記録として扱い，`status: "duplicate"`を返してしまうため，その音声は二度と処理されない．クライアントは`duplicate`応答を受け取った時点で端末からファイルを削除する想定のため，実質的に音声が失われる．

### 修正

- `app/pipeline/orchestrator.py`: 実処理を`_process_uploaded_audio_inner`に分離し，`process_uploaded_audio`全体をtry/exceptで囲んだ．例外発生時は`logging`で記録した上で，`UploadRecord.status`を`"failed"`に更新する．
- `app/api/upload.py`: 冪等性チェックに`_is_retryable`判定を追加した．
  - `status == "failed"`の記録は常に再試行を許可する．
  - `status == "processing"`のまま30分(`_STALE_PROCESSING_TIMEOUT`)を超えて更新されていない記録も，サーバー異常終了等で処理が中断された可能性があるとみなし再試行を許可する(例外を介さずプロセスごと落ちた場合への対策)．
  - `"completed"`・`"rejected"`は結果が変わらないため再試行の対象としない．
  - 再試行時は新しい`UploadRecord`を作らず，既存の記録を`"processing"`に戻して使い回す(同じ`upload_record_id`を維持する)．

### 動作確認

意図的に不正な音声データ(テキストファイル)をアップロードし，`UploadRecord.status`が`"failed"`になることを確認した．続けて同じファイルを再送すると，`"duplicate"`ではなく`"accepted"`として受理され，同じ`upload_record_id`で再試行されることを確認した．

## B. 同時アップロードによる500エラー

### 問題

重複チェック(SELECT)とアップロード記録の登録(INSERT)の間に競合状態があり，同一内容のファイルが同時にアップロードされると，`UploadRecord`の一意制約(`user_id`, `content_sha256`)違反による`IntegrityError`が発生し，500エラーになる．

### 修正

`app/api/upload.py`の新規作成時のコミットを`try/except IntegrityError`で囲み，競合が発生した場合はロールバックの上，先にコミットされた記録を再取得して`"duplicate"`レスポンスを返すよう変更した．

## C. タイムゾーンの扱い

### 問題

- DBの`DateTime`列はタイムゾーン情報を持たない(naive)．APIレスポンスもタイムゾーン情報なしでシリアライズされるため，クライアントが「サーバーのローカル時刻」なのか「UTC」なのか判断できず，誤って解釈する可能性があった．
- `app/api/chat.py`がGemini APIに渡す会話記録のタイムスタンプがUTCのままであり，日本時間(JST)との9時間のずれにより「何時から？」等の質問に対する回答が誤っていた．また，現在の日時を渡していないため「今日」「明日」等の相対的な表現を正しく解釈できなかった．

### 修正

`app/timeutil.py`を新設し，「DBに保存されるdatetimeは常にUTCである」という規約をコード上に明示した．

- `parse_client_datetime`: クライアントから送られたISO8601文字列(タイムゾーン付き・なしのいずれも)を，naiveなUTCのdatetimeに正規化する．`app/api/upload.py`の`recorded_started_at`解析に適用した．
- `as_utc_aware`: DBから取得したnaiveなUTCのdatetimeに，明示的に`tzinfo=UTC`を付与する．APIレスポンス(`app/api/browse.py`の会話一覧・会話詳細・発言一覧，`app/api/chat.py`の`references`)に適用し，JSONシリアライズ時に明示的なUTCオフセット(例: `2026-11-06T13:09:42+00:00`)が付くようにした．
- `to_jst`・`now_jst`: UTCのdatetimeを日本時間に変換する．`app/api/chat.py`のGemini APIへのプロンプト構築で，各発言のタイムスタンプを日本時間に変換し，さらに「現在の日時は(日本時間)です」という一文を追加した．

### 動作確認

- `GET /api/conversations`のレスポンスで，`started_at`等に明示的なUTCオフセット(`Z`)が付くことを確認した．
- 「ランチの話は何時頃でしたか?」という質問に対し，UTC 13:09の発言が日本時間22:09として正しく回答に反映されることを確認した(修正前は13:09のまま，9時間のずれが生じていた)．

## ブラウザフロントエンドの利用方法

`programs/server/README.md`に「4. ブラウザでの利用」の章を追加した．アカウント登録・ログイン・質問する/過去の会話を聞く/話者の名前を設定の3タブの使い方，ログアウト方法を記載した．

## テスト

`tests/test_server.py`に以下のユニットテストを追加し，全20件が合格することを確認した．

- `_is_retryable`の4パターン(failed許可，completed/rejected拒否，直近processing拒否，古いprocessing許可)
- `parse_client_datetime`のタイムゾーン正規化
- `as_utc_aware`・`to_jst`の変換結果

## 未解決の論点・次に検討すべき事項

- `_STALE_PROCESSING_TIMEOUT`(30分)は暫定値であり，実際の処理時間(Gemini APIのレート制限によるリトライ等)に応じた調整が必要になる可能性がある．
- 失敗の種類(一時的なAPIエラーか，恒久的な音声データの問題か)を区別していないため，恒久的に失敗する音声(例: 完全に無音，破損したファイル)は再試行のたびに同じ失敗を繰り返す．失敗回数の記録・上限の導入を検討する余地がある．
- 競合時の再試行(B)はユーザーに通知されないため，クライアント側が"duplicate"レスポンスをどう扱うかは別途仕様化が必要．
