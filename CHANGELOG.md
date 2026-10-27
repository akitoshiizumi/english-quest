# 変更履歴

この履歴は利用者から見える主な機能変更をチケット単位で記録します。各項目は対応する実装コミットにリンクしています。

## 2026-10-26
### T-080: Show the nearest words beside vocabulary preview candidates

- Each preview candidate now shows up to three distinct nearest indexed words with cosine scores beside its add/exclusion status; exact top-three ranking remains safe-bound pruned and does not change the threshold rule.
- Verification: embedding unit tests (6 passed), HTTP integration tests (35 passed), preview E2E (1 passed), and production build. No live API call was made. Implementation commit: `5116230`.

### T-079: Prevent duplicate vocabulary registration

- The registration button now blocks repeat clicks while pending, stays locked after success, and becomes available after a failed request. Candidate registration is idempotent under concurrent submissions and normalized duplicates, with no extra vocabulary or sense rows.
- Verification: database migration tests (14 passed), HTTP integration tests (35 passed; simultaneous duplicate registration creates one vocabulary/sense pair), and targeted E2E tests (4 passed). Production build and `git diff --check` passed. Implementation commit: `dc4c10d`.

## 2026-10-25
### T-078: Batch vocabulary preview similarity checks and show progress

- Vocabulary preview now compares candidates in sequential batches of 50 with visible progress, retryable batch errors, aggregated usage/job writes, and safe cosine-bound pruning to reduce exact comparisons.
- Verification: embedding unit tests (5 passed), HTTP integration tests (35 passed), and targeted preview E2E tests (3 passed). `npm.cmd test` passed build, Python, keyboard, distribution, and audio stages; E2E was 37/39 due to two unrelated existing overlap/practice timeouts. No paid API was called. Implementation commit: `28eeffc`.

### T-077: Index all missing vocabulary similarity embeddings

- The similarity index action now processes all eligible missing senses in repeated 100-item batches, displays live indexed/remaining counts, refreshes the estimate on completion, and allows retry after failures while retaining completed batches.
- Verification: targeted embedding unit test (3 passed); full Python tests (90 passed); similarity-index E2E (2 passed). `npm.cmd test` passed build, Python, keyboard, distribution, and audio tests; E2E was 35/37 due to two unrelated overlap/practice timeouts. No paid API was called. Implementation commit: `117d07a`.

### T-076: Rename the reported audio file with its JST timestamp

- Renamed the identified legacy audio artifact from its UTC timestamp to JST and updated its sole SQLite reference. Its audio bytes and unique suffix were preserved; the live detail and playback endpoints now use the JST filename.
- Verification: SQLite backup created; the detail endpoint returned the new name and audio endpoint served 9,221,325 bytes with the identical SHA-256. Documentation record commit: `0fb7414`.

### T-075: Use JST timestamps in generated audio filenames

- Newly generated audio filenames now use JST wall time while keeping their unique suffix; previously generated filenames are unchanged.
- Verification: `py -m unittest tests.test_storage_and_pages -v` passed (8 tests); `py -m unittest discover` passed (89 tests); `git diff --check` passed. Implementation commit: `abf3c59`.

### T-074: Show saved material creation timestamps

- Restored the saved-material creation date in the overlap details by including SQLite `created_at_utc` in the material detail response; legacy and DB-only materials now display their creation time in JST.
- Verification: `py -m unittest discover` passed (88 tests); timestamp API integration tests (2) and material details E2E (1) passed; `npm.cmd run build` and `git diff --check` passed. Implementation commit: `84841d0`.

### T-073: Make SQLite the sole source of truth for saved materials

- Structured material content, including summaries and subtitle/timing data, is now read and written in SQLite. Existing legacy JSON is imported once and retained as an inert recovery artifact; new generation saves structured content only in the database and keeps audio binaries in files. The two material lists now show the same database records.
- Verification: `py -m unittest discover` passed (88 tests); relevant saved-material and overlap E2E passed (4 tests); `npm.cmd run build` and `git diff --check` passed. No live OpenAI requests or production data were used. Implementation commit: `5df5ca1`.


### T-072: Make saved JSON authoritative for title and AI summary

- Saved file titles, article text, AI summaries, and summary provenance now follow the matching `practice_data` JSON. Explicit summary updates use that JSON body, generate the title and Japanese summary together, and save them to JSON before reconciling the SQLite projection. Body edits invalidate stale summaries and audio timings.
- Verification: `py -m unittest discover` passed (88 tests); saved-material summary E2E passed (1 test); `npm.cmd run build` and `git diff --check` passed. No live OpenAI request or production JSON was changed. Implementation commit: `495d23f`.

### T-071: Use practice_data as the saved-material list source

- Both screens now show the same valid practice_data JSON files, display each filename, omit DB-only rows, and offer a refresh button. Lists refresh when reopened and after generation.
- Verification: `npm.cmd test` passed (85 Python, 3 keyboard, 3 distribution, 1 audio-clip, 35 E2E tests); `git diff --check` passed. Implementation commit: `c7e5aa7`.

## 2026-10-25

### T-068: Rename the application to English Learning Studio

- Updated the app header, browser title, Windows launcher labels, README, and current product-facing references to `English Learning Studio`; kept Overlap as the feature name.
- Verification: `npm.cmd test` passed (build, 83 Python, 3 keyboard, 3 statistics distribution, 1 audio clip, 33 Playwright tests); `git diff --check` passed. Implementation commit: ef0c8a2.

### T-067: Remove duplicate legacy descriptions from saved material details

- Saved-material details now show the AI summary as the only description line. Counts, creation date, audio details, cost, and the no-summary state remain; source metadata is not changed.
- Verification: targeted saved-material E2E and `npm.cmd run build` passed. `npm.cmd test` ran 32/33 Playwright tests; the unrelated database restore scenario hit intermittent Windows `WinError 5` replacing its temporary SQLite file. No paid API was called. Implementation commit: 9cb3749.

### T-066: Make automatic CEFR assessment resilient to incomplete JSON

- Increased the Responses output allowance from 160 to 512 tokens and aligned the preflight cost reserve. Incomplete or malformed CEFR responses now fail with a useful retry message instead of a JSON decoder exception, their API-reported token usage is recorded, and completed vocabulary remains checkpointed for resume.
- Verification: Python 83 tests passed; build, keyboard 3, statistics distribution 3, and audio clip 1 passed. `npm.cmd test` ran 32/33 Playwright tests; the unrelated database restore test hit Windows `WinError 5` while replacing its temporary SQLite file. No paid API was called. Implementation commit: 7a17d76.


### T-064: Select due vocabulary for review practice

- Vocabulary practice can select only due items from the latest answer per vocabulary and direction. The existing simple-interval-v1 and Tokyo date rules are shared with dashboard statistics; due items sort oldest first, and the standard mode remains available for new words.
- Verification: `npm.cmd test` passed (build, 81 Python, 3 keyboard, 3 distribution, 1 audio clip, 33 Playwright tests); `git diff --check` passed. Tests use isolated synthetic fixtures. Implementation commit: b04123a.

### T-065: Add focus mode to vocabulary practice

- Added an optional practice focus view that hides navigation and configuration while keeping the question, history, progress, answer/rating controls, and exit button available. Escape and the exit button restore the full view without resetting the question.
- Verification: `npm.cmd test` passed (build, 81 Python, 3 keyboard, 3 distribution, 1 audio clip, 33 Playwright tests); `git diff --check` passed. Tests use isolated synthetic fixtures. Implementation commit: b04123a.


### T-063: Show AI summaries in saved material details

- The overlap metadata panel now shows the saved AI summary with a clear not-yet-generated state. Legacy saved-file descriptions are kept separate and are not mislabeled as AI summaries; viewing details makes no API call.
- Verification: `npm.cmd test` passed (build, 79 Python, 3 keyboard, 3 distribution, 1 audio-clip, 31 Playwright tests); `git diff --check` passed. Automated checks used isolated data and no paid API. Implementation commit: `8808ac5`.

### T-062: Make the saved-material lists show the same materials

- Both the overlap saved-material selector and vocabulary-management table now list the same database records and show their total. Legacy saved JSON files register idempotently; text-only materials appear with playback controls disabled. Existing media files are not changed by synchronization.
- Verification: `npm.cmd test` passed (build, 78 Python, 3 keyboard, 3 distribution, 1 audio-clip, 30 Playwright tests); `git diff --check` passed. Uses isolated fixtures, with no production DB or paid API calls. Implementation commit: `3dfbee1`.

### T-061: Add AI summaries to saved material metadata

- Added an explicit generate/update action and visible AI summary for each saved material. The summary and generation provenance are stored in material metadata; title/text edits invalidate stale summaries. API usage and estimated cost are recorded, and failures preserve existing metadata.
- Verification: `npm.cmd test` passed (TypeScript/Vite build, 76 Python, 3 keyboard, 3 distribution, 1 audio-clip, 29 Playwright tests), using deterministic fixtures and no paid API calls. Implementation commit: `128ccd8`.

### T-060: Delete a saved learning material

- Added a confirmed delete action for saved materials. It removes material links and unshared generated audio/subtitle files in the active materials folder, while preserving vocabulary and learning history. Shared and out-of-folder files are protected.
- Verification: `npm.cmd test` passed (build, 70 Python, 3 keyboard, 3 distribution unit, 1 audio-clip, 28 Playwright tests), using isolated fixtures. Implementation commit: `da05a77`.

### T-059: Explore vocabulary performance distributions

- Added an interactive vocabulary histogram with selectable self-reported accuracy, attempt count, known count, and retry count on the horizontal axis and vocabulary totals on the vertical axis. Accuracy excludes unseen words and reports them separately; count distributions include them in the zero bin. Search filters the distribution.
- Verification: `npm.cmd test` passed (build, 67 Python, 3 keyboard, 3 distribution unit, 1 audio-clip, 28 Playwright tests), using isolated synthetic fixtures. Implementation commit: `91bb822`.

### T-058: Add graph views to vocabulary and daily learning results

- The dashboard now switches vocabulary results and date-based learning activity between their tables and bar charts. Vocabulary charts show known/retry counts and known rate, while daily charts show answers or study time by activity. Empty results, narrow screens, and long labels are handled.
- Verification: `npm.cmd test` passed (build, 67 Python, 3 keyboard, 1 audio-clip, 28 Playwright tests), using isolated synthetic fixtures. Implementation commit: `617c83e`.

### T-057: Show progress while generating audio and subtitles

- Audio/subtitle generation now streams phase updates and displays an estimated percentage at roughly 1% increments. Audio chunks and completed transcription chunks inform the estimate; the UI marks it as approximate and reports completion or errors.
- Verification: `npm.cmd test` passed (TypeScript/Vite build, 67 Python, 3 keyboard, 1 audio-clip, 28 Playwright tests), with synthetic fixtures and mocked providers only. Implementation commit hash will be added in the documentation follow-up.

### T-056: Keep sentence repeat active during sentence navigation

- A/W sentence navigation now preserves the active repeat selection. Repeat remains controlled by its configured key (R by default) and the sentence repeat button.
- Verification: `npm.cmd test` passed (build, 66 Python, 3 keyboard, 1 audio-clip, 27 Playwright tests). Implementation commit hash will be added in the documentation follow-up.

### T-055: Keep the focused sentence at the top of the transcript

- When audio focus advances to a different sentence, the enabled transcript follow now aligns that sentence block with the top of the scrolling area. Every development change now starts with an indexed ticket.
- Verification: `npm.cmd test` passed (build, 66 Python, 3 keyboard, 1 audio-clip, 27 Playwright tests); one earlier run hit a transient unrelated Windows database-restore `WinError 5`. Implementation commit hash will be added in the documentation follow-up.

### T-054: Expand the interface with the available screen width

- The centered app area now grows to 1920px, and the overlap transcript/sidebar columns scale with the viewport while narrow layouts remain stacked.
- Verification: `npm.cmd test` passed (build, 66 Python, 3 keyboard, 1 audio-clip, 27 Playwright tests), using isolated fixtures. Implementation commit: `9419e6e`.

### T-053: Configure sentence navigation and keep playback controls visible

- Added configurable A/W sentence navigation and a sticky playback/settings sidebar beside the scrollable transcript. Settings and key assignments persist, and shortcuts respect editable fields and composition state.
- Verification: `npm.cmd test` passed (build, 66 Python, 3 keyboard, 1 audio-clip, 26 Playwright tests), using isolated fixtures. Implementation commit: `88f3b3b`.

### T-052: Keep study material generation resilient to non-Japanese notes

- Clarified Japanese-only translation and meaning instructions with a field-specific retry. If foreign text remains, the generator removes it, keeps the usable article, and omits vocabulary notes that no longer have a Japanese meaning.
- Verification: `npm.cmd test` passed (build, 66 Python, 3 keyboard, 1 audio clip, 25 Playwright tests), using fixed Responses fixtures and isolated E2E data. Implementation commit: `db1792b`.

## 2026-10-24

### T-051: Add per-word and article generation modes

- Added a choice between one sentence per selected vocabulary item and one cohesive article using all selected vocabulary. Article-wide coverage is checked and missing terms get one completion pass; the mode is retained in job and saved-material metadata.
- Verification: `npm.cmd test` passed (build, 61 Python, 3 keyboard, 1 audio clip, 25 Playwright tests), using deterministic provider fixtures and isolated E2E data. Implementation commit: `9bee0bc`.


### T-050: Show JST times and streamline generated study sets

- Saved overlap timestamps now show JST in the list and detail view. Generated study sets auto-save with vocabulary links; edited text stays in sync with the saved parent and overlap editor. The explicit save button is removed and the generated-text editor is taller.
- Verification: `npm.cmd test` passed (build, 58 Python, 3 keyboard, 1 audio-clip, 25 Playwright tests), using isolated E2E data. Implementation commit: `a88e489`.

### T-049: Handle placeholders and special characters in vocabulary generation

- Prompts now treat trailing `?`, `?`, `~`, `?`, and `...` as open phrase slots and validate the English stem (for example, `rave about ?` matches `rave about`).
- Coverage failures store missing target names separately from the explanatory error. Legacy failures no longer repeat the error as a fake target. Regex metacharacters remain literal.
- Verification: `npm.cmd test` passed (build, 58 Python, 3 keyboard, 1 audio-clip, 25 Playwright tests); deterministic fixtures only. Implementation commit: `06d4a70`.

### T-048: Show study-set generation failure reasons

- Failed generation now displays the API error and missing target words, including after page reload; retry remains available.
- Verification: `npm.cmd test` passed (build, 54 Python, 3 keyboard, 1 audio-clip, 25 Playwright tests), using isolated job fixtures. Implementation commit: `f41baf1`.

### T-047: Include no-history vocabulary in study-set plans

- The short-history option now includes words with no answers, including when an accuracy ceiling is set; accuracy is undefined for those words.
- Updated filter wording and added integration/E2E coverage for a category with no answer history.
- Verification: `npm.cmd test` passed (build, 53 Python, 3 keyboard, 1 audio-clip, 25 Playwright tests). Implementation commit: `74e407e`.

### T-046: Explain empty study-set filter results

- Empty study-set plans show why no words matched and recommend which filters to loosen.
- The planner reports directional answer-history coverage and labels legacy history as direction-unknown and excluded.
- Verification: `npm.cmd test` passed (build, 52 Python, 3 keyboard, 1 audio-clip, 24 Playwright tests). Implementation commit: `5a3d551`.

### T-045: Restore study-set vocabulary results with active filters

- Study-set planning keeps studied vocabulary available to recent-history filters and applies eligibility before limiting the requested count.
- Integration and Playwright tests cover all-category and selected-category plans with late matching words.
- Verification: `npm.cmd test` passed (build, 51 Python, 3 keyboard, 1 audio-clip, 23 Playwright tests). Implementation commit: `495be96`.

### 英語学習サービスへの拡張（T-001〜T-019）

| チケット | 変更内容 | 実装コミット |
|---|---|---|
| T-001 | 既存データと教材の互換性を調査し、移行条件を定義 | `b83e87f` |
| T-002 | バージョン管理付きデータ移行、バックアップ、復元を追加 | `74ebe12` |
| T-003 | 機能分割と共通の学習画面基盤を追加 | `9d17f37` |
| T-004 | OpenAI API接続設定、使用量・費用記録を追加 | `ae59af3` |
| T-005 | 日→英・英→日の語彙学習と回答履歴を追加 | `3879d37` |
| T-006 | 複数キー割り当て可能なキーボード操作と案内を追加 | `fc7cacf` |
| T-007 | 語彙・練習教材の検索、編集、アーカイブを追加 | `24ad807` |
| T-008 | 復習予定と基本統計を追加 | `0708566` |
| T-009 | 語義ごとのCEFR難易度自動評価と再開可能な処理を追加 | `723214c` |
| T-010 | 語彙候補の抽出、重複確認、ベクトル類似判定を追加 | `bb1496f` |
| T-011 | 選択語彙を含む練習英文の生成を追加 | `1b44481` |
| T-012 | オーバーラッピング再生時間の記録を追加 | `9ffc0c8` |
| T-013 | 苦手語彙から教材生成・音声練習までを連携 | `f77a958` |
| T-014 | 合成データによる統合テスト・Playwright E2E基盤を追加 | `f109995` |
| T-015 | GUIをReact + TypeScriptへ移行 | `4ed3a8a` |
| T-016 | 機能別タブとデータベース管理画面を追加 | `9348af1` |
| T-017 | 語彙練習内に教材作成フィルターを統合 | `389fa00` |
| T-018 | CEFR難易度の一括自動評価を追加 | `bb33715` |
| T-019 | 語彙練習・オーバーラッピング時間の分離統計、期間選択、再送時の二重計上防止を追加 | `fd38c43` |
| T-020 | テスト教材を一時保存先へ隔離し、画面に本番/テストの保存先を表示 | `73d4bff`, `eaa251e` |
| T-021 | 全タブのデザインを統一し、語彙カードを大きく表示。モバイル表示にも対応 | `fc8500f` |

T-021までの検証: `npm.cmd test` 成功（Python 44件、キーボード3件、Playwright 13件）。`py -m compileall -q english_overlap tests` と `git diff --check` も成功。

### UXレビュー対応

| チケット | 変更内容 | 実装コミット |
|---|---|---|
| T-022 | UXレビューとPlaywright表示検査を行い、優先課題をT-023/T-024へ分割 | `b534d4b` |
| T-023 | 語彙練習の状態とキー設定に追従するショートカット案内を追加 | `1fd7207` |
| T-024 | 語彙練習の進捗・完了・空セット状態を表示 | `b62f7d0` |
| T-025 | フィルター語彙からの英文作成をオーバーラッピング画面に配置 | `509b581` |

### T-026: AI開発チケットの完了条件と検証記録を標準化

- チケットテンプレートを追加し、受け入れ条件・テスト層・fixture・実行証跡の記入を標準化。
- process-ticket Skillを更新し、新規チケット作成、完了判定、再発防止の運用を明記。
- ドキュメント検証: テンプレート必須欄、Skill同期、git diff --check は成功。
- Unit / integration / E2E: 文書のみの変更のため対象外。
- Implementation commit: `9632be9`。

### T-027〜T-029: 語彙練習・統計・語彙管理の改善チケット

- 語彙練習の対象上限1000件、直近N回の自己評価率、全回不正解フィルターを要求化。
- 学習統計の独立ダッシュボード化を要求化。
- 語彙管理のソート・50件ページングを要求化し、狭い画面向けカード表示などの案を記録。
- 要求仕様と操作ガイドを更新。実装・テストは各チケットで行う。
- チケット作成コミット: `96b9f16`。

### T-028 要求追加: 語彙データベースの学習実績

- ダッシュボードにDB登録数、登場数、正解/不正解数、正解率、未登場語数を追加。
- 語彙別の登場・正誤件数と正解率を比較できる条件を追加。DB全体の累積値と期間集計を区別する。
- 正解率の分母、未学習語・旧履歴の扱いをテスト条件に含める。
- T-028更新コミット: `40057e2`。

### T-027: 語彙練習の件数上限と履歴フィルター

- 最大1000件の練習件数と、直近N回の自己評価率・全回不正解のフィルターを追加。
- N回未満の履歴を含めるか選べるようにした。
- `npm.cmd test` 成功。
- 実装コミット: `8f32788`。

### T-028: 学習ダッシュボードとデータベース統計

- 学習統計を独立ページへ移し、期間別学習推移・時間・復習状況を表示。
- DB全体の語彙数・語義数・登場/正誤件数・累積自己評価率・未登場語数を追加。
- 語彙別の登場数・正誤件数・正解率を検索・並べ替えできる一覧を追加。
- `npm.cmd test` 成功（Playwright 17 tests）。
- 実装コミット: `c96d4a3`。

### T-029: 語彙管理のソートと50件ページング

- 語彙管理に英語・日本語・品詞・タグ・CEFRのソートを追加。
- サーバー側で50件ずつ取得し、範囲・総件数・ページ移動を表示。検索条件を維持。
- 125件の合成fixtureでAPIページ境界とPlaywrightの一覧操作を確認。
- `npm.cmd test` 成功（Playwright 18 tests）。
- 実装コミット: `8777fd3`。

### T-030: Learning dashboard statistics resilience

- Keep period and daily statistics visible if all-time aggregate fields are missing; show local fallbacks in affected sections.
- Add isolated API contract checks and Playwright coverage for complete and partial responses.
- Verification: `npm.cmd test` passed (build, 46 Python tests, 3 keyboard tests, 18 E2E tests). Implementation commit: 6b41190.

### T-031: Vocabulary management sorting

- Sorted displayed tags by the visible tag fallback, discarded stale HTTP results, and verified actual ascending/descending row order across pages.
- Verification: HTTP integration and Playwright row-order checks passed.
- Implementation commit: 15fa110.

### T-032: Eligible practice count

- The start request now returns a fixed list of distinct eligible vocabulary IDs up to the configured maximum. Progress uses the actual selected total; last-answer-incorrect filtering is direction-specific.
- Verification: HTTP checks cover category with one word, last incorrect results, multiple senses, and direction isolation. Playwright confirms 1/1 with a 1000 request.
- Implementation commit: d80e599.

### T-033: Practice O/X answer history

- The active card now shows the last 12 direction-specific answer results at its upper right; O means known and X means again. The full history length is exposed as a title.
- Verification: HTTP history order and Playwright visible X/accessible label checks passed.
- Implementation commit: 3fe9812.

### T-034: Remove test overlap materials

- Removed 120 confirmed test JSON files and 120 matching audio files. Fixed the generation endpoint to write to its configured save directory, so test servers remain isolated.
- Verification: Temporary-storage integration check passed; after full suite, production practice_data contains 3 JSON and 3 audio files and zero fixture texts.
- Implementation commit: d81094d.

### T-035: Overlap playback and sentence annotations

- Space toggles playback on the overlap page outside editable controls. Each saved/generated sentence displays English, Japanese translation, and vocabulary notes; the active sentence follows the audio.
- Verification: Playwright checks saved fixture translation, vocabulary, and Space play/pause. Full build and E2E passed.
- Implementation commit: 555c302.

### T-036: Advanced native conversation speech style

- Added a selectable hardest overlap voice condition using fast, heavily reduced native conversation with brief mild mumbling. The Realtime prompt keeps the supplied text and avoids exaggerated slurring.
- Verification: `npm.cmd test` passed, including the synthetic WebSocket payload test, isolated configuration API test, and Playwright selector test (20 E2E tests). Implementation commit: `4701143`.

### T-037: One-sentence overlap repeat

- Each sentence card can repeat its own audio span. R toggles the sentence at the playback position, and the active target is highlighted. Back, restart, word seek, and new-material load clear the repeat target.
- Untimed sentences show a disabled control and explanatory message instead of an inaccurate loop.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 21 Playwright tests). Implementation commit: `179305f`.

### T-038: Stable rapid-answer ordering

- Recent-answer filters, visible history, and statistics now resolve same-time answers by insertion order. New vocabulary answers record microsecond timestamps.
- Verification: forced same-time HTTP fixture, targeted migration check, and full `npm.cmd test` passed. Implementation commit: `48a8219`.

### T-039: Space playback and a pause between sentence repeats

- Space now pauses and resumes audio even when a sentence repeat button retains focus. Enter and R continue to control sentence repeat.
- Each sentence repeat pauses audio for one second. Space during that interval stops the pending replay; a second Space resumes from the sentence start.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 21 Playwright tests), including the focused-button and timed-gap E2E path. Implementation commit: `9e96280`.

### T-040: Longer silence and a sentence lead-in

- Sentence repeats now include 1.5 seconds of silence and restart 0.25 seconds before the first timed word, clamped to the beginning of the audio.
- The same lead-in is used for initial selection, automatic repeat, and Space resume. R keeps the intended sentence selected during the lead-in.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 21 Playwright tests). Implementation commit: `c22e719`.

### T-041: Stop repeats before the next sentence

- Repeats now stop at the earlier of shortly after the selected sentence's last timed word or before the next sentence's first timed word. Invalid, tightly spaced ranges remain unavailable.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 21 Playwright tests), including early-stop and close-timestamp fixtures. Implementation commit: `c614ad9`.

### T-042: Play only the selected sentence audio

- Sentence repeat now uses a clipped audio file ending at the selected sentence's final word timestamp, capped at the next sentence start. The 0.15-second early-stop offset and callback-based stopping are removed.
- The 0.25-second lead-in, 1.5-second gap, Space/R controls, and full-audio restoration remain available.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 1 audio-clip, 21 Playwright tests), using an audible two-tone fixture. Implementation commit: `11ee89c`.

### T-043: Simplify dashboard inventory counts

- The all-time per-vocabulary performance table is closed by default and can be opened or closed by mouse or keyboard.
- Equal vocabulary, learning-target, and sense totals are displayed once as `語彙`; distinct totals retain clear separate labels. In the current database each count is 16,920.
- Verification: `npm.cmd test` passed (49 Python, 3 keyboard, 1 audio-clip, 21 Playwright tests), including equal and distinct count cases. Implementation commit: `8d10fd7`.

### T-044: Add direct page navigation and study-set filters

- Vocabulary management accepts a page number, including direct jumps to distant pages.
- Study-set themes are selected from dataset categories; planning supports recent answer count and self-rated accuracy filters, with optional short-history inclusion.
- Verification: `npm.cmd test` passed (50 Python, 3 keyboard, 1 audio-clip, 22 Playwright tests). Implementation commit: `7fc8b19`.

- T-055 implementation commit: `ab33be8`.

- T-056 implementation commit: `057cc3f`.

- T-057 implementation commit: `bee7f1b`.
