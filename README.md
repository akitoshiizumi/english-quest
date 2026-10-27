# English Quest

語彙学習から、自分専用の英文・音声教材での実践まで。
覚える・聞く・声に出す・復習するをひとつにつなぐ英語学習アプリです。

- **語彙練習**：英→日・日→英、苦手語の絞り込み、復習期限に合わせた出題。
- **語彙管理・追加**：英単語と意味の編集、英文からの候補抽出、CEFR難易度の管理。
- **教材作成・重ね読み**：選んだ語彙を使う英文を作成し、音声・字幕と一緒に練習。
- **学習ダッシュボード**：語彙ごとの実績、学習時間、目標と進捗を確認。

## 開発計画

英語学習サービスへの拡張に関する[要求仕様・設計・チケット](docs/README.md)を管理しています。

変更内容は[変更履歴](CHANGELOG.md)を参照してください。

## cloneして使う

Windowsでは **Python 3.10以上**（Python Launcherの `py` コマンドを含む）とGitを用意してください。

```powershell
git clone https://github.com/akitoshiizumi/english-quest.git
cd english-quest
.\start_windows.bat
```

起動ファイルを実行すると、サーバーが起動してブラウザが開きます。
初回だけ、同梱データベースを `dataset/vocab.db` に復元します。
データの準備が完了してからブラウザが開きます。
画面のURLは http://127.0.0.1:8765 です。終了するときはサーバーのウィンドウで `Ctrl+C` を押します。

**17,163件の語彙と14件の音声教材を同梱**しているため、APIキーなしで語彙練習と保存教材の再生を始められます。
Git LFS、Node.js、追加のPythonパッケージは通常利用には不要です。
cloneしたファイルに加え、初回のデータベース復元用に約140MBの空き容量が必要です。
同梱データには作成元の学習履歴・設定も含まれます。

手動起動やmacOS/Linuxでは、Python 3.10以上で次を実行し、上記URLを開きます。

```sh
python server.py
```

## AI機能を使う場合

英文・音声・訳・語彙候補・難易度などのAI生成にはOpenAI APIキーとインターネット接続が必要です。
`.env.example` を `.env` にコピーし、`OPENAI_API_KEY=` に自分のキーを設定して再起動してください。
API利用料がかかります。キーを設定した状態では、CEFR自動評価も画面の設定に従って動作します。
音声の新規生成には、追加でFFmpegをインストールして `ffmpeg` コマンドをPATHに通してください。
音声生成用のPythonパッケージもインストールします。

```powershell
py -m pip install -r requirements.txt
```

画面はReact + TypeScriptで作成し、ビルド済みの静的ファイルをPythonサーバーが配信します。通常の利用時にNode.jsサーバーは起動しません。ビルド成果物は `english_overlap/static/app/` に含めます。開発時はNode.js 20.19以上で `npm ci` の後に `npm run dev` を使えます。画面変更後は `npm run build` で成果物を更新してください。

APIキーを `config.json` やGitへ保存しないでください。`.env` はGit管理対象外です。
`practice_data/` の教材音声・既存JSONはGitに含めています。
稼働中の `dataset/vocab.db`、バックアップ、ログ、開発用依存パッケージは配布対象外です。

## プロジェクト構成

- `server.py`: サーバー起動だけを担当するエントリーポイント
- `english_overlap/app.py`: HTTP処理、OpenAI API連携、音声・字幕保存のアプリ本体
- `english_overlap/__init__.py`: Pythonパッケージ定義
- `frontend/src/`: React + TypeScriptのブラウザ画面
- `english_overlap/static/app/`: Pythonサーバーから配信するビルド成果物
- `config.json`: 話し方と初期英文の設定
- `.env`: APIキー（Git管理対象外）
- `.env.example`: APIキーを設定するときのひな形
- `requirements.txt`: Pythonの追加依存パッケージ
- `dataset/starter/`: 初回起動時に復元する分割圧縮データベース
- `practice_data/`: Git管理される同梱教材と、新しく生成した音声

## 使用しているAPI・モデル

### 音声生成

- API: OpenAI Realtime API（WebSocket）
- モデル: `gpt-realtime-2.1-mini`
- 出力: 24kHz PCM音声を内部WAVとして受信し、保存・再生時にMP3へ変換
- 英文を、設定したアメリカ英語の話し方で読み上げます。

### 日本語訳・語彙説明

- API: OpenAI Responses API
- モデル: `gpt-5.4-mini`
- 出力: Structured Outputs（JSON Schema）
- 英文を文ごとに分け、日本語訳と難しい語彙・表現の説明を自動生成します。
- 音声には日本語訳や説明は含めず、英語だけを読み上げます。

### 単語タイムスタンプ

- API: OpenAI Audio Transcriptions API
- モデル: `whisper-1`
- `verbose_json` と word timestamps を使用します。
- 長い音声は30秒ごとに分割して文字起こしし、元の音声時間へ戻して同期します。

### 料金

生成時に以下の料金を合算して表示・JSON保存します。

- Realtime APIの音声・テキストトークン料金
- Responses API（`gpt-5.4-mini`）の入力・出力トークン料金
- Audio Transcriptions API（`whisper-1`）の音声時間料金

料金はコード内の設定レートによる目安です。最新料金はOpenAIの料金表を確認してください。

## Saved data

Structured material data is stored in `dataset/vocab.db`. On the first launch after cloning, the server restores this file from the checksummed, split gzip snapshot in `dataset/starter/`. An existing database is never overwritten. Custom databases configured with `ENGLISH_OVERLAP_DB` and test databases are not seeded automatically. Existing subtitle JSON files are imported once on the first material-list request after the schema migration; the database keeps their text, summaries, transcript blocks, word timings, and generation metadata. The import records each source filename and digest, so later changes to those old JSON files do not overwrite database edits. Invalid files are retained and reported in the material status.

`practice_data/` stores generated audio binaries. The folder is shown in the interface as the audio-file location and can be changed with `ENGLISH_OVERLAP_PRODUCTION_DATA_DIR` (the legacy `ENGLISH_OVERLAP_DATA_DIR` setting is still accepted). Tests use an isolated folder selected with `ENGLISH_OVERLAP_DATA_ROLE=test` and `ENGLISH_OVERLAP_TEST_DATA_DIR`.

Saved materials play without calling an API: subtitle and timing data load from SQLite, and the referenced audio file loads from `practice_data/`.

## 設定

`config.json` の `SPEECH_STYLES` で、アメリカ英語の話し方を編集できます。

速度はすべて `1.0` 固定です。話し方の違いが、速度差ではなく抑揚・連結・弱形・感情の違いになるようにしています。

## 参考

- [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [Realtime API](https://developers.openai.com/api/docs/guides/realtime)
- [Audio Transcriptions API](https://developers.openai.com/api/docs/guides/speech-to-text)
