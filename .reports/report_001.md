# EchoMindServer ベンチマークレポート(ex001_model_benchmark)

## 1. 目的

本レポートは，`仕様書.md`で定義されたEchoMindサーバーの実装に先立ち，サーバーの音声処理パイプラインで使用する各要素技術(VAD・話者分離・音声認識・ベクトル検索)について，候補モデルの精度を比較評価した結果をまとめたものである．評価は`programs/ex001_model_benchmark/`で実施した．

## 2. ベンチマーク用データ

日本語・複数話者・話者分離済みの無料公開コーパスは確認できなかったため，JVSコーパス(日本語100話者の単一話者音声コーパス，`juxtnorth/katachi-benchmarks`が提供する16kHz版を使用)のnonpara30サブセット(BASIC5000文章セット，話者ごとに異なる30文が収録されている)を用いて，疑似複数話者会話データを人工的に構築した．

`programs/ex001_model_benchmark/data.py`により，2〜3名の話者からそれぞれ3〜5発話をランダムに選び，0.4〜1.2秒の無音を挟んで結合することで，発話区間・話者ID・発話テキストの正解ラベルが既知の疑似会話を30件生成した(`datasets/ex001_model_benchmark/synthetic/`)．

この方法で作成したデータは，実際の会話に存在する重複発話や環境雑音，残響を含まないため，各手法の相対比較には有効であるが，絶対的な精度は実運用環境と異なる可能性がある．

## 3. VAD(音声区間検出)の比較

対象: Silero VAD, WebRTC VAD(感度2)．
評価: 疑似会話30件のフレーム単位(20ms)Precision/Recall/F1．

| 手法 | Precision | Recall | F1 |
| :--- | :--- | :--- | :--- |
| WebRTC VAD | 0.9999 | 0.7054 | 0.8261 |
| Silero VAD | 1.0000 | 0.6960 | 0.8197 |

両手法ともPrecisionは非常に高いが，Recallが0.70程度にとどまっている．これは，発話の立ち上がり・立ち下がり付近で検出漏れが生じやすいためと考えられる．両手法の差はわずかであり，本データでは明確な優劣は確認できなかった．

結果グラフ: `outputs/ex001_model_benchmark/vad/comparison.png`
詳細結果: `outputs/ex001_model_benchmark/vad/{webrtcvad,silero_vad}/metrics.json`

## 4. 話者分離の比較

対象: `pyannote/speaker-diarization-3.1`．
評価: 疑似会話30件のDER(Diarization Error Rate，低いほど良い)．

| 手法 | 平均DER |
| :--- | :--- |
| pyannote 3.1 | 0.3671 |

`pyannote/speaker-diarization-community-1`は，本環境にインストールした`pyannote.audio==3.3.2`ではパイプライン初期化引数(`plda`)が非互換であり評価できなかった．community-1を利用するには，CUDAツールキットおよびhuggingface_hubを含む多数の依存ライブラリをメジャーバージョンアップする必要があり，Haas-ja等が依存する共有環境を破壊するリスクがあるため，本ベンチマークでは見送った．community-1を評価する場合は，別の仮想環境を用意した上で再度の検証が必要である．

pyannote 3.1のDER=0.367は，仕様書が想定する実運用(専門用語の多い会話，複数人のやり取り)に対してやや高い値であり，改善の余地がある．ただし，本ベンチマークの疑似会話データは無音区間の挿入のみで重複発話を含まないため，実際の会話よりも話者分離が容易な条件である点に注意が必要である．

結果グラフ: `outputs/ex001_model_benchmark/diarization/comparison.png`
詳細結果: `outputs/ex001_model_benchmark/diarization/pyannote_3.1/metrics.json`

## 5. 音声認識(ASR)の比較

対象: `Haas-ja-v1.0`(仕様書記載)，`kotoba-whisper-v1.0`，`whisper-large-v3`．
評価: JVS BASIC5000発話からランダムに抽出した200件に対するCER(文字誤り率，低いほど良い)．

| 手法 | 平均CER |
| :--- | :--- |
| Haas-ja-v1.0 | 0.1178 |
| whisper-large-v3 | 0.1453 |
| kotoba-whisper-v1.0 | 0.1628 |

仕様書で指定されているHaas-ja-v1.0が，比較対象の中で最も低いCERを達成した．当初計画していた`reazonspeech-nemo-v2`は，NeMo独自のロード方式が必要で評価コストが高いため，より標準的な`transformers`パイプラインで扱える`whisper-large-v3`に代替した．

結果グラフ: `outputs/ex001_model_benchmark/asr/comparison.png`
詳細結果: `outputs/ex001_model_benchmark/asr/{haas_ja,kotoba_whisper_v1_0,whisper_large_v3}/metrics.json`(各発話のreference/hypothesis/CERを含む)

## 6. ベクトル検索(文章埋め込み)の比較

対象: `ruri-base`，`ruri-large-v2`(仕様書記載)，`multilingual-e5-large`．
評価: 疑似会話30件・281発話をコーパスとし，各発話内容からGemini APIで生成した質問281件に対する検索精度(Recall@k, MRR)．

| 手法 | MRR | Recall@1 | Recall@3 | Recall@5 |
| :--- | :--- | :--- | :--- | :--- |
| ruri-large-v2 | 0.9562 | 0.9253 | 0.9893 | 0.9893 |
| multilingual-e5-large | 0.9525 | 0.9146 | 0.9929 | 0.9929 |
| ruri-base | 0.9497 | 0.9181 | 0.9822 | 0.9858 |

3手法とも高い検索精度を示したが，MRRおよびRecall@1ではruri-large-v2が最も高く，仕様書記載のモデルで十分な精度が得られることを確認した．

結果グラフ: `outputs/ex001_model_benchmark/embedding/comparison.png`
詳細結果: `outputs/ex001_model_benchmark/embedding/{ruri_base,ruri_large_v2,multilingual_e5_large}/metrics.json`
質問生成キャッシュ: `outputs/ex001_model_benchmark/embedding/queries_cache.json`

## 7. モデル選定の提案

- **音声認識**: 仕様書記載の`Haas-ja-v1.0`を採用する．本ベンチマークでも最良のCERを示しており，専門用語に対するカスタム辞書機能(`haas_asr.Vocabulary`)も利用できる．
- **ベクトル検索**: 仕様書記載の`ruri-large-v2`を採用する．MRR・Recall@1で最良であった．
- **話者分離**: 仕様書記載の`pyannote/speaker-diarization-3.1`を暫定的に採用する．ただし，DER=0.367はやや高く，community-1の評価結果とあわせて再検討する価値がある．
- **VAD**: WebRTC VADとSilero VADに有意な差はなかった．実装の簡便さから，依存ライブラリの少ないSilero VADの採用を提案する．

## 8. 未解決の論点・次に検討すべき事項

- `pyannote/speaker-diarization-community-1`は，本環境と依存関係が競合するため未評価である．別の仮想環境(新しいCUDAツールキット・huggingface_hub等)を用意した上で，pyannote 3.1との精度比較を行う必要がある．
- 本ベンチマークの疑似会話データは，無音区間の挿入のみで重複発話(オーバーラップ)や環境雑音を含んでいない．実環境に近いノイズ・重複発話を含むデータでの再評価が望ましい．
- `reazonspeech-nemo-v2`は未評価である．NeMoのネイティブAPIでの評価スクリプトを別途用意すれば比較可能である．
- 話者ID統合(pyannoteの一時的話者IDを人物IDへ紐づける処理)および名前推定の精度評価は未実施である．サーバー実装時に合わせて検証が必要である．
- 以上の結果を踏まえ，`programs/server/`にてEchoMindサーバー本体(FastAPI, PostgreSQL+pgvector)の実装に着手する．
