# OpenAI APIの選定・更新方針

ユーザー要求: OpenAI APIはできるだけ最新を使う。

## 運用ルール

1. API機能の実装・モデル更新に着手する際、公式のAPI仕様、モデル一覧、廃止予定を確認する。実装完了時に採用情報を記録する。
2. 用途に合う現行の安定したAPI・モデルを優先する。最新モデルに必要機能がない場合は、理由を記録して対応モデルを使う。プレビューの採用は安定性・費用・必要機能を比較して判断する。
3. APIの世代とモデルの新しさを別々に確認する。モデル名だけを置き換えて完了にしない。
4. 用途ごとにモデルを設定できるようにし、結果には実際のモデル、プロンプト版、生成日を保持する。料金は確認日・レート版を持つ。
5. 音声では単語タイムスタンプ、対応音声形式、話し方指定を確認する。新モデルへの変更で字幕同期を壊さない。
6. Embeddingsのモデル変更は再計算を伴う。旧・新ベクトルは比較しない。
7. 非推奨化や新モデル公開を受けて更新チケットを作り、互換性・品質・費用を確認して切り替える。アプリが無検証で自動更新する方式にはしない。

## 用途

テキスト生成・候補抽出・難易度判定、埋め込み、音声生成、文字起こしを個別に選定する。テキスト生成の検討起点はResponses API。音声・埋め込みは各専用APIの最新仕様を確認する。

## 選定記録の必須項目

用途 / APIとバージョン・SDK / モデルID / 公式資料URL / 確認日 / 必須機能 / 品質と費用 / 採用理由 / 例外と更新条件。

## 今回の資料確認

2026-10-24に以下の公式資料を確認した。今回は開発方針の整備であり、モデル選定・切り替えは未実施。コード中の既存モデルを最新と認定したものではない。

- [Responses API](https://developers.openai.com/api/reference/responses/overview)
- [モデル一覧](https://developers.openai.com/api/docs/models/all)
- [廃止・非推奨情報](https://developers.openai.com/api/docs/deprecations)

## 実装時の選定記録（2026-10-24）

| 用途 | API / モデル | 根拠・価格 | 採用理由・例外 |
|---|---|---|---|
| 翻訳・英文・語彙抽出・CEFR判定 | Responses API / `gpt-6-luna` | [モデル一覧](https://developers.openai.com/api/docs/models)、[価格](https://developers.openai.com/api/docs/pricing)。通常レートは入力 $0.10 / 100万token、出力 $0.50 / 100万token | 最新のGPT-6系列から、候補抽出など高件数処理の単価を優先。用途別環境変数 `OPENAI_TEXT_MODEL` で更新可能 |
| 音声生成 | Realtime API WebSocket / `gpt-realtime-2.1-mini` | [Realtime model](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)、[Realtime guide](https://developers.openai.com/api/docs/guides/realtime-conversations)、[価格](https://developers.openai.com/api/docs/pricing) | 既存24kHz PCM、音声スタイル、字幕タイムラインの互換性を維持。最新候補のGPT-Live 1は新しいLive session protocolで現行Realtime WebSocketと異なるため、別途移行・音質・中断・費用の検証が必要。Live 1の表示価格は $0.05/分 |
| 単語時刻 | Audio Transcriptions API / `whisper-1` | [文字起こし仕様](https://developers.openai.com/api/docs/guides/speech-to-text)、[API参照](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create) | `verbose_json` と `timestamp_granularities[]=word` は現在Whisperのみ。公式資料ではWhisperと他の旧文字起こしモデルは2027-02-26に停止予定。現時点の移行例外であり、停止日前に単語時刻を得る代替手段を評価する |
| ベクトル類似度 | Embeddings API / `text-embedding-3-small` | [Embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)、[モデル一覧](https://developers.openai.com/api/docs/models/text-embedding-3-small)。2026-10-27確認。$0.02 / 100万input token、APIの標準出力は1536次元 | 768次元をAPIへ指定し、既存値は切り詰め・正規化して移行する。異なるモデル・次元・入力空間のベクトルは比較しない。1000件から選んだ語の一部比較で、上位5件は1536次元の89.2%と一致 |

価格は2026-10-24の公式表示を固定メモとして記録した。実請求前に現在のPricingを確認する。音声料金はモデル別token単価・使用量に応じて変わるため、利用前概算として提示し、完了後はAPI返却usageから推定記録を行う。

コードの用途別モデル設定は `OPENAI_TEXT_MODEL`、`OPENAI_REALTIME_MODEL`、`OPENAI_TRANSCRIPTION_MODEL`、`OPENAI_EMBEDDING_MODEL`。自動テストは固定応答を使い、有料APIを呼ばない。

## Saved material AI summaries (2026-10-25)

- API: Responses API (`POST /v1/responses`) with Structured Outputs through `text.format` JSON Schema. [Text generation](https://developers.openai.com/api/docs/guides/text), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
- Model: `OPENAI_TEXT_MODEL`, default `gpt-6-luna`.
- Rationale: Reuse the existing text-generation model setting, Responses API connection, and estimated-cost calculation; validate the generated summary against a schema.
- Invocation: Only an explicit user action calls the API. Record usage from any response that returns it, including malformed output. Automated tests use deterministic responses.

T-072 keeps the same Responses API, configured text model, and Structured Outputs `text.format` schema. The request body is now only the matching practice_data JSON text; the structured result contains a title and Japanese summary, persisted with provenance in that JSON. The official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) confirms `text.format` JSON Schema for Responses.
