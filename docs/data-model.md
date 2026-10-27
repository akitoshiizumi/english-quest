# データ設計案

## 現状調査（2026-10-24、読み取りのみ）

dataset/vocab.db:

| テーブル | 件数 | 内容 |
|---|---:|---|
| vocab | 16,920 | vocab_id、english、japanese、mnemonic、tags、example_sentence、cefr_level、pos、日時、genre_tags、sources、source_count |
| history | 14,085 | id、vocab_id、score、result、appeared_count、correct_count、appeared_time、session_id、created_at |
| similar | 50,760 | vocab_id、similar_vocab_id、similarity、created_at |

cefr_levelは全件未設定（NULL 3,384件、空文字13,536件）。`tags`には`TOEIC600`、`oreilly`など出典・コース名が入る一方、`genre_tags`には`TechnologyAndIT`、`DailyLife`などテーマ分類が入る。`tags`はカテゴリそのものではないため、ユーザー向けカテゴリ定義と複数タグの扱いを設ける。両列は現状単一テキストで索引は`tags`のみ。

history.resultはOK 8,370件、NG 5,715件。scoreはOKでも約4.5〜100、NGでも約-0.001〜75で、resultと単純なしきい値の関係は保証できない。appeared_count / correct_countの定義も確認できない。方向列がなく、日時は秒精度の`YYYY-MM-DD HH:MM:SS`だがタイムゾーン不明。appeared_timeは分精度、session_idは`YYYYMMDD-HHMM`の例を確認。38組で同じvocab_id・session_id・created_atの複数行があるため、これらの列だけで旧行を重複排除しない。語彙学習の方向別習熟度や新形式の回答へ機械変換せず、旧履歴として保持する。

similarは片方向の複合主キーで、外部キーはvocab_idにしか設定されていない。実データの孤児参照は0件だが、逆方向レコードがない行が24,174件あるため、対称関係として扱えない。similarityは約0.329〜1.00000024。モデル、ベクトル次元、対象テキスト、作成方法は不明であり、新しい埋め込み判定へ流用しない。新しいベクトルは生成条件をメタデータ化する。

practice_dataのJSON 3件すべてがversion=2で構文として有効。MP3 3件すべてがJSONから参照され、欠損はなかった。JSONは本文、blocks、語彙、単語時刻、音声ファイル、料金などを持つ。確認日は2026-10-24。音声・JSONは今後もファイルで保持し、DBに参照を持つ案。

## 論理モデル（DDLはT-002で確定）

| エンティティ | 主な情報 |
|---|---|
| vocabulary | 既存vocab_id、英語表記、正規化表記、品詞、状態。表記だけのUNIQUE制約は設けない |
| senses | 語彙ID、日本語の意味、例文、出典。既存japaneseの分割可否は調査後に決める |
| difficulty | 語義ID、推定CEFR、根拠、判定モデル・日付、手動指定、判定版 |
| materials / material_vocabulary | 教材ID、本文、JSON・音声パス、使用語彙・語義ID、難易度、生成条件 |
| study_sessions / study_events | セッション、種別、語彙・語義または教材、方向、自己評価、回答時間、活動時間、UTC日時、重複防止ID |
| review_state | 語義IDと方向、復習予定、習熟状態、アルゴリズム版 |
| embeddings | 語彙・語義ID、モデル、次元、入力形式版、入力ハッシュ、ベクトル、作成日 |
| import_batches / candidates | 入力と出典、候補、選択状態、除外理由、類似先・スコア、処理状況 |
| api_jobs / api_usage | 用途、状態、再開位置、モデル、使用量、料金レート版、失敗理由 |
| settings / schema_migrations | キー割り当て、用途別モデル等の非秘密設定、スキーマ履歴 |

## 整合性ルール

- 語彙難易度と個人習熟度を別々に保持する。旧履歴は元情報を保持し、方向不明を「不明」とする。
- タイムスタンプは新規分をUTCで保存し、日別集計の境界をAsia/Tokyoで決める。旧日時はタイムゾーン不明として元の値を保ち、UTC変換したと装わない。
- 異なるモデル・次元・入力形式のベクトルを直接比較しない。変更時は再計算ジョブを作る。ゼロベクトル・欠損は判定不能として扱う。
- 完全一致は表記だけで異義語を削除しない。表記・品詞・意味の比較規則をT-010で決める。
- 通常の削除操作はアーカイブとし、履歴と教材の語彙参照を保つ。画面から復元できる。物理削除は画面から提供せず、将来必要なら専用保守手順と整合性確認を行う。
- スキーマ変更前にDBと関連ファイルをバックアップする。移行は再実行可能にし、トランザクションと版で管理する。
- 本番教材は `practice_data/`（または `ENGLISH_OVERLAP_PRODUCTION_DATA_DIR`）に保存する。テストは `ENGLISH_OVERLAP_DATA_ROLE=test` と `ENGLISH_OVERLAP_TEST_DATA_DIR` で明示した隔離先のみを使用し、テスト用保存先がない場合は本番へフォールバックせずエラーにする。既存の `ENGLISH_OVERLAP_DATA_DIR` は本番保存先の互換設定として扱う。

## 実装済みデータ基盤（schema version 2）

`english_overlap.database`が`ENGLISH_OVERLAP_DB`環境変数（未設定時`dataset/vocab.db`）を開く。サーバー起動時は未適用移行の前にSQLite backup APIでDB全体をバックアップし、各版をトランザクション内で適用する。最新バージョンなら新規バックアップは作らない。移行後は`python -m english_overlap.database backup`で明示バックアップ、`restore <file> --to <path>`でquick_check済みバックアップの原子的復元ができ、復元前のDBも安全コピーに保存する。

version 1は既存`vocab`を正本のまま保ち、既存japanese・pos・example_sentenceから一語彙一語義の初期`senses`を作り、`genre_tags`を初期`categories`と`vocabulary_categories`へ写す。version 2は`study_sessions`、重複防止キー付き`study_events`、`materials`、`material_vocabulary`を作る。旧`history`と`similar`は変換せず保持する。テストは合成の3テーブルfixtureを使う。

## Saved material content

SQLite `materials` is the sole source of truth for structured material fields. `title`, `text_content`, `audio_path`, and `created_at_utc` are queryable columns. `content_json` stores subtitle data such as spoken text, blocks, transcript, word timings, summary and its provenance, voice/style/model, counts, duration, and cost. `metadata_json` remains for application metadata such as study-set grouping. The audio binary remains a separate file referenced by `audio_path`.

Migration version 5 adds `content_json` and `material_legacy_imports`. On first material-list access after schema migration, valid legacy subtitle JSON files are imported once. Existing DB material IDs, archived state, and vocabulary links are preserved; JSON-only records receive new IDs. Each imported source name and SHA-256 digest is recorded. Invalid files remain untouched and are returned as import warnings. The importer ignores any source already recorded, so later edits to old JSON cannot overwrite DB changes. Legacy JSON files are retained as inert migration artifacts and are not read for playback, listing, editing, summary generation, or deletion.

New speech generation writes only audio binaries to `practice_data`; generated audio filenames use the creation timestamp in JST (`YYYYMMDD_HHMMSS`) plus a unique suffix. subtitle and timing payloads are stored in `materials.content_json`. Playback fetches that payload by `material_id` and retrieves audio by the DB audio reference. Title/body edits update SQLite; body edits clear stale summary/timings and detach the old audio reference without deleting its file. Summary generation reads the DB text and stores title, summary, and provenance in SQLite. Material lists include DB records directly and do not depend on legacy file membership.

## Cumulative learning goals

T-070 stores independent overlap-hours and distinct-vocabulary targets in the existing `app_settings` table. Progress is derived from all `study_events`: summed `overlap_activity.duration_seconds` and distinct `vocab_id` values with at least one `vocabulary_answer`. It is lifetime progress and does not use the selected dashboard date range. Older legacy history without these events or durations is excluded.
