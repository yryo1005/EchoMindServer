# EchoMindServer 終了フラグ(処理状況ポーリング)機能の追加

## 1. 目的

音声アップロードの処理はバックグラウンドで非同期に実行されるため，`POST /api/upload`の応答(受付完了のみ)だけでは，クライアントは処理がいつ完了したかを知ることができない．サーバーで処理が正常に完了した時点でクライアント側の音声ファイルを削除する運用に変更するにあたり，クライアントが安全に削除してよいタイミングを判断できる仕組みを追加した．

## 2. 実装内容

`GET /api/upload/{upload_record_id}/status`を`app/api/upload.py`に追加した．

```json
{
  "upload_record_id": "...",
  "status": "processing" | "completed" | "rejected" | "failed",
  "is_finished": true | false,
  "safe_to_delete_client_copy": true | false,
  "conversation_id": "..." または null
}
```

- `is_finished`: サーバー側の処理がこれ以上進まない最終状態(`completed`/`rejected`/`failed`)に達したかどうか．
- `safe_to_delete_client_copy`(終了フラグ): クライアントが端末上の音声ファイルを削除してよいかどうか．
  - `completed`(正常に会話として保存された)・`rejected`(発話が検出されなかった，または話者が1名のみで「会話」として扱われなかった．再送しても結果は変わらない)の場合に`true`．
  - `failed`(処理中にエラーが発生した)の場合は`false`のまま．`.reports/report_007.md`で実装した再試行機構により，同じファイルを再送すれば自動的に再試行されるため，クライアントはファイルを保持しておく必要がある．
  - `processing`の場合も`false`．

認証を必須とし，自分のアカウントのアップロード記録以外は404として扱う(他アカウントへの情報漏洩を防ぐ)．

既存の`POST /api/upload`が重複アップロード時に返す`"status": "duplicate"`レスポンスにも，同じ`safe_to_delete_client_copy`フィールドを追加し，クライアントがどちらのエンドポイントからでも同じ基準で削除判断できるようにした．

## 3. クライアント側の想定フロー

`programs/server/README.md`に推奨フローを記載した．

1. `POST /api/upload`で音声をアップロードし，`upload_record_id`を保持する．
2. `GET /api/upload/{upload_record_id}/status`を一定間隔でポーリングする．
3. `safe_to_delete_client_copy`が`true`になった時点で端末上の音声ファイルを削除する．`false`のまま`is_finished`が`true`(つまり`failed`)の場合は，しばらくしてから同じファイルを再アップロードする．

## 4. 動作確認

- アップロード直後に`GET /api/upload/{id}/status`を呼び出すと，`status: "processing"`，`is_finished: false`，`safe_to_delete_client_copy: false`が返ることを確認した．
- 処理完了後に同じエンドポイントを呼び出すと，`status: "completed"`，`is_finished: true`，`safe_to_delete_client_copy: true`，`conversation_id`に作成された会話のIDが返ることを確認した．
- 他のアカウントのアクセストークンでこのエンドポイントを呼び出すと404が返り，認証トークンなしでは401が返ることを確認した．

テスト: `tests/test_server.py`に`_build_upload_status`の4状態(completed/rejected/failed/processing)に対するユニットテストを追加し，全24件が合格することを確認した．

## 5. 未解決の論点・次に検討すべき事項

- 現状はクライアントによるポーリング方式である．より即時性を求める場合，WebSocket/Server-Sent Events等によるプッシュ通知方式への変更も検討できるが，iPhoneアプリ自体が本タスクの対象外であるため，現時点ではポーリングを採用した．
- ポーリング間隔はクライアント実装側の判断に委ねている．サーバー側でレート制限等は設けていない．
- `failed`のまま何度再試行しても恒久的に失敗する音声(例: 破損したファイル)については，`.reports/report_007.md`の「未解決の論点」で述べた失敗回数の記録・上限の導入と合わせて検討する必要がある(現状は無限に再試行され続ける)．
