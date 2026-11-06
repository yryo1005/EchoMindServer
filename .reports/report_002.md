# EchoMindServer ベンチマークレポート(ex002_model_benchmark)

## 1. 目的

本レポートは，`.reports/report_001.md`(ex001_model_benchmark)で実施したモデル選定の信ぴょう性を高めるため，比較対象モデルの追加およびテストデータの拡充・多様化を行った再評価の結果をまとめたものである．評価は`programs/ex002_model_benchmark/`で実施した．

## 2. ex001からの変更点

### 2.1 テストデータの拡充・多様化

- 疑似会話の件数を30件から80件に増やした．
- 話者数を2〜3名から2〜4名に増やし，発話数も話者ごとに3〜5発話から3〜6発話に増やした．
- ex001では発話間に無音のみを挟んでいたが，ex002では30%の確率で発話同士を重複(オーバーラップ)させ，複数人が同時に話す状況を再現した．
- 加算的white noiseを混入させ(SNR 10〜25dB)，ノイズのある環境を再現した．

これにより，ASRの評価サンプル数もJVS BASIC5000から200件→400件に拡大した．ベクトル検索の検索対象コーパスは281発話から1096発話に拡大した(質問生成はAPIコスト抑制のため，このうち400件をランダムにサンプリングして実施)．

### 2.2 比較対象モデルの追加

| タスク | ex001 | ex002で追加 |
| :--- | :--- | :--- |
| VAD | WebRTC VAD, Silero VAD | `pyannote/segmentation-3.0`ベースのVAD |
| 話者分離 | pyannote 3.1 | `pyannote/speaker-diarization-community-1`(別仮想環境`.venv_diarization_community`で評価) |
| 音声認識 | Haas-ja, kotoba-whisper, whisper-large-v3 | `reazonspeech-nemo-v2` |
| 文章埋め込み | ruri-base, ruri-large-v2, multilingual-e5-large | `multilingual-e5-base`, `pkshatech/GLuCoSE-base-ja` |

community-1は，`pyannote.audio==3.3.2`(Haas-ja等が依存する`.venv_ml`)とAPIが非互換(`pyannote.audio>=4.0`が必要)であったため，別の仮想環境`.venv_diarization_community`(`pyannote.audio==4.0.7`)を用意して評価した．

## 3. VAD(音声区間検出)の比較

| 手法 | Precision | Recall | F1 | F1の標準偏差 |
| :--- | :--- | :--- | :--- | :--- |
| WebRTC VAD | 1.0000 | 0.6965 | 0.8205 | 0.0265 |
| Silero VAD | 1.0000 | 0.7516 | 0.8576 | 0.0259 |
| pyannote segmentation-3.0 | 1.0000 | 0.7521 | 0.8578 | 0.0297 |

重複発話・ノイズを含むデータでも，WebRTC VADに対してSilero VADとpyannote segmentationが明確に高いRecall(0.75前後)を示した．両者の差はごくわずかであり，統計的に有意な差とは言えない．ex001(重複・ノイズなし)と比べてSilero VADのF1が0.820→0.858へ向上している点は意外だが，これはより長い発話が多く生成されたこと等のデータ分布の違いによる可能性があり，単純な比較はできない．

結果グラフ: `outputs/ex002_model_benchmark/vad/comparison.png`

## 4. 話者分離の比較

| 手法 | 平均DER | DERの標準偏差 |
| :--- | :--- | :--- |
| pyannote 3.1 | 0.3793 | 0.1022 |
| pyannote community-1 | 0.3932 | 0.1137 |

community-1は，公式のベンチマーク(AISHELL-4, AMI等)では3.1より明確に改善しているとされるが，本ベンチマーク(重複発話・ノイズを含む疑似会話)では3.1の方がわずかに良好であった．両者の差(0.014)は標準偏差(0.10前後)に比べて小さく，80件のサンプルでは統計的に有意な差とは言い難い．重複発話を多く含む条件はcommunity-1が想定する評価条件(AMI, DIHARD等)と異なる可能性があり，この結果だけで3.1が優れていると判断するのは早計である．

結果グラフ: `outputs/ex002_model_benchmark/diarization/comparison.png`

## 5. 音声認識(ASR)の比較

| 手法 | 平均CER | CERの標準偏差 |
| :--- | :--- | :--- |
| reazonspeech-nemo-v2 | 0.1151 | 0.1214 |
| Haas-ja-v1.0 | 0.1191 | 0.1145 |
| whisper-large-v3 | 0.1419 | 0.1230 |
| kotoba-whisper-v1.0 | 0.1593 | 0.1134 |

サンプル数を200件から400件に拡大した結果，ex001で最良であったHaas-ja-v1.0をreazonspeech-nemo-v2がわずかに上回った(0.1151 vs 0.1191)．ただし両者の差(0.004)はCERの標準偏差(0.11〜0.12)に比べて非常に小さく，この2モデルの優劣について統計的に明確な結論は出せない．whisper-large-v3とkotoba-whisper-v1.0は，両実験を通じて一貫してこの2モデルより劣っている．

結果グラフ: `outputs/ex002_model_benchmark/asr/comparison.png`，`outputs/ex002_model_benchmark/asr/comparison_vs_ex001.png`(ex001との比較)

## 6. ベクトル検索(文章埋め込み)の比較

| 手法 | MRR | Recall@1 | Recall@3 | Recall@5 |
| :--- | :--- | :--- | :--- | :--- |
| ruri-base | 0.8482 | 0.730 | 0.9725 | 0.985 |
| GLuCoSE-base-ja | 0.8467 | 0.740 | 0.960 | 0.9725 |
| ruri-large-v2 | 0.8448 | 0.7275 | 0.975 | 0.985 |
| multilingual-e5-large | 0.8367 | 0.710 | 0.9725 | 0.98 |
| multilingual-e5-base | 0.8301 | 0.7025 | 0.965 | 0.9775 |

検索対象コーパスを281発話から1096発話に拡大したことで，全手法のMRRがex001(0.95前後)からex002(0.83〜0.85)へ大きく低下した．これは検索対象が増え，類似した内容の発話が混在しやすくなったためであり，より現実的な検索難易度での評価と言える．この条件下では，ruri-base・GLuCoSE-base-ja・ruri-large-v2の3手法が僅差で上位であり，仕様書記載のruri-large-v2が必ずしも最良とは言えない結果となった．ただし差は小さく，400件のサンプルでは明確な優劣と言うには心許ない．

結果グラフ: `outputs/ex002_model_benchmark/embedding/comparison.png`

## 7. モデル選定の再検討

ex001と比べて，いずれのタスクにおいても最上位モデル間の差が評価データのばらつき(標準偏差)より小さく，「単一の最良モデル」を断定するにはサンプル数・条件の面でなお不十分であることが分かった．一方で，以下の傾向は両実験を通じて一貫していた．

- **音声認識**: Haas-ja-v1.0とreazonspeech-nemo-v2が同程度に良好で，whisper-large-v3・kotoba-whisper-v1.0より明確に優れている．仕様書記載のHaas-ja-v1.0を採用しつつ，reazonspeech-nemo-v2をフォールバック候補として記録する．
- **ベクトル検索**: ruri系(base/large-v2)とGLuCoSE-base-jaが僅差で上位，multilingual-e5系がやや劣る．仕様書記載のruri-large-v2を採用するが，ruri-baseの方が計算コストが低く同等の精度であるため，速度要件次第ではruri-baseも有力な選択肢である．
- **話者分離**: pyannote 3.1とcommunity-1に明確な優劣は確認できなかった．仕様書記載のpyannote 3.1を採用する．
- **VAD**: Silero VADとpyannote segmentation-3.0が同程度に良好で，WebRTC VADより明確に優れている．依存ライブラリの軽さからSilero VADを推奨する．

## 8. 未解決の論点・次に検討すべき事項

- 本ベンチマークの疑似会話データは，JVSコーパス(クリーンな朗読音声)を混合したものであり，実際の自然な会話音声(言い淀み，相槌，方言等)とは性質が異なる．実データでの検証が望ましい．
- 上位モデル間の差が統計的に有意かどうかを判断するため，疑似会話データをさらに増やす，または複数のシード値で複数回生成し有意差検定(例: paired t-test)を行うことが望ましい．
- 専門用語に対するHaas-jaのカスタム辞書機能(`haas_asr.Vocabulary`)の効果は未検証である．
- community-1の評価環境(`.venv_diarization_community`)は`.venv_ml`と重複する部分が多く，将来的に`.venv_ml`自体を`pyannote.audio>=4.0`に統一できないか検討する価値がある(Haas-ja等との互換性を要確認)．
- 以上の結果を踏まえ，`programs/server/`にてEchoMindサーバー本体(FastAPI, PostgreSQL+pgvector)の実装に着手する．
