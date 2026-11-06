# Order 004

## ユーザーからの指示（原文）

もう少し広い範囲でモデルを選定したりテストしてモデル選択の信ぴょう性を高めたいです

(AskUserQuestionでの回答: 「比較対象モデルを増やす」「テストデータを拡充・多様化する」を優先)

## 指示の解釈

Order 001〜003で実施したex001_model_benchmarkの結果だけでは，モデル選定の根拠として十分な信ぴょう性が得られないとの指摘である．ユーザーの選択に基づき，以下の2点を優先して拡張する．

1. **比較対象モデルの追加**
   - VAD: `pyannote/segmentation-3.0`を追加
   - 話者分離: `pyannote/speaker-diarization-community-1`を，依存関係が競合しない別の仮想環境(`.venv_diarization_community`)を用意した上で追加評価する
   - 音声認識: `reazonspeech-nemo-v2`を追加(NeMoベースで`.venv_ml`に追加インストール可能)
   - 文章埋め込み: `intfloat/multilingual-e5-base`，`pkshatech/GLuCoSE-base-ja`等を追加

2. **テストデータの拡充・多様化**
   - 疑似会話の件数・話者数・発話数を増やす
   - これまでの疑似会話は無音区間の挿入のみであったため，発話の重複(オーバーラップ)および背景雑音(加算的ノイズ)を加えた，より実環境に近い条件のデータを追加する

モデル構造・データ生成方法ともに本質的な変更を伴うため，`@.ai/ai-dev-kit/machine_learning.md`の規則に従い，実験の通し番号を`ex001`から`ex002`に変更する(`programs/ex002_model_benchmark/`)．ex001の結果は削除せず保持し，ex002の結果と合わせて比較する．
