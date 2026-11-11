# Order 012

## ユーザーからの指示（原文）

サーバーで音声を受け取り処理が正常に完了した際にクライアント側の音声を削除することにします
終了フラグをクライアントに送る機能を追加してください

## 指示の解釈

アップロード処理はバックグラウンドで非同期に実行されるため，`POST /api/upload`の応答だけではクライアントは処理の完了を知ることができない．クライアントが端末上の録音ファイルを安全に削除できるタイミングを判断できるよう，処理状況をポーリングできるエンドポイントを追加する．

`GET /api/upload/{upload_record_id}/status`を新設し，`is_finished`(処理が最終状態に達したか)と`safe_to_delete_client_copy`(終了フラグ，クライアントが音声を削除してよいか)を返す．

- `completed`(正常完了)・`rejected`(会話として扱われないと判定済み，再送しても結果は変わらない)は`safe_to_delete_client_copy=true`．
- `failed`(処理中にエラーが発生，Order 011で再試行対象とした状態)は`safe_to_delete_client_copy=false`とし，クライアントがファイルを保持して再送できるようにする．
- `processing`は`is_finished=false`．

既存の`POST /api/upload`の重複(`duplicate`)レスポンスにも同じフラグを追加し，一貫性を持たせた．
