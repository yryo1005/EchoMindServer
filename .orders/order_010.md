# Order 010

## ユーザーからの指示（原文）

https://echomind.stargazyguys.com/healthでStatus ofと出ました

README.mdにサーバーの起動方法や公開方法をまとめておいてください

## 指示の解釈

Cloudflare Tunnel経由での公開(Order 009)が正常に動作することを確認できたとの報告．これを踏まえ，`programs/server/README.md`に，DB起動・サーバー起動(systemdサービス化を含む)・Cloudflare Tunnelでの公開手順・既存データの移行・テスト・停止方法をまとめた．`document.md`からもこのREADMEへのリンクを追加した．
