# 要求仕様 v0.1

更新日: 2026-10-25

## 目的と初期範囲

語彙の登録、語彙学習、語彙を使った英文作成、オーバーラッピング、学習の振り返りを一つのサービスで行う。初期実装はWindows上のローカル利用・単一学習者を前提とする設計案。複数ユーザー、公開運用、発音採点、自由記述の自動採点は追加要求として扱う。

優先度P0は共通基盤、P1は最初の学習機能、P2は続く拡張。いずれも今回の開発対象。

| ID | 優先度 | 要求 | 受け入れ条件 |
|---|---|---|---|
| DATA-001 | P0 | 既存データを引き継ぐ | 語彙IDと既存ファイルを保持し、移行前後の件数・参照整合性を確認できる。旧履歴の不明な意味を推測で変換しない |
| DATA-002 | P0 | データ変更を安全に管理する | スキーマ版、移行履歴、バックアップ・復元手順があり、失敗時に部分移行が残らない |
| DATA-003 | P1 | 語彙・教材を管理する | 検索、絞り込み、意味・品詞・タグ・出典の編集、アーカイブ、エクスポートができる。履歴を残したまま学習対象から外せる |
| DATA-005 | P1 | 語彙一覧をソート・ページ移動する | 語彙管理一覧を列で昇順・降順ソートでき、1ページ50行で前後・先頭・末尾へ移動できる。ページ番号を直接指定でき、検索条件を保ち、表示範囲と全件数を確認できる |
| DATA-006 | P1 | 保存済み教材を削除する | 確認後に教材と語彙リンクを削除できる。語彙本体・学習履歴は保持し、教材専用の音声・字幕ファイルは安全に削除する。他教材と共有されるファイル、保存先外のファイルは削除しない |
| DATA-007 | P1 | 保存済み教材にAI要約を付ける | ファイル付き教材のJSONに保存した本文を正本として、明示操作で教材名とAI要約を生成・更新する。教材名・要約・生成元モデル・プロンプト版・日時を同じJSONに保存し、DBには一覧検索用に反映する。一覧表示ではAPIを呼び出さない。編集はJSONを更新し、古い要約を無効にする。失敗時はファイルと利用者データを保持し、使用量・料金を記録する
| DATA-008 | P1 | 保存済み教材の一覧と件数を一致させる | practice_data内の有効な教材JSONファイルを正本として、オーバーラッピングと語彙管理に同じ一覧・順序・件数を表示し、各JSONファイル名も表示する。DB行のないJSONは重複なく登録し、JSONファイルのないDB教材は一覧から除外する
| DATA-009 | P1 | Show AI summaries in saved material details | The overlap saved-material metadata panel displays the AI summary as the only description line, clearly identifies materials with no generated AI summary, and displays remaining metadata; opening details makes no API call |
| DATA-004 | P1 | テスト教材と本番教材を分離する | 本番起動時は本番保存先のみを一覧・読込・保存し、自動テストは独立した一時保存先だけを使う。既存の本番教材を保持し、保存先を画面・設定で識別できる |
| VOC-001 | P1 | 日→英／英→日で学習する | 方向を選択でき、問題→答え→自己評価→次問をマウスでもキーでも完了できる。日→英では対応する意味・品詞を示す |
| VOC-002 | P1 | 語彙練習の対象数と履歴条件を指定する | 1セッションの対象語数は最大1000。過去N回の正解率（自己評価率）と全回不正解を条件に対象を絞り込め、履歴不足の語の扱いを明示できる |
| UI-001 | P1 | 単純な共通操作 | A/U、S/Iの2組で学習でき、ボタンから同じ操作ができる。入力中の誤発火・長押しを防ぐ |
| UI-002 | P1 | キーを設定する | 1操作に複数キーを割り当て、保存・復元・初期化できる。同一状態内の競合を検知する |
| UI-005 | P2 | Focus the vocabulary practice screen | Optional focus mode hides unrelated application UI while keeping the prompt, answer, history, progress, and answer/rating controls available; mouse and Escape can exit and restore the full page. |
| LOG-001 | P1 | 学習履歴を記録する | 語彙ID、方向、日時、自己評価、回答時間、セッションを保存し、二重送信で記録が重複しない |
| REVIEW-001 | P2 | Review due vocabulary | Vocabulary practice offers a due-only target based on the latest answer per vocabulary and direction; due items are sorted oldest due date first; standard practice still supports new vocabulary. The simple-interval-v1 schedule and Tokyo-day boundary are consistent with dashboard due items. |
| STAT-001 | P2 | 学習統計を確認する | 日別学習数、方向別の「覚えていた」率、活動時間、学習日数、復習予定を表示。自己評価率と明記し、旧履歴は区別する |
| STAT-002 | P2 | 学習機能ごとの時間を確認する | 語彙練習とオーバーラッピングの活動時間を別々に日別・期間別で表示し、合計も確認できる。二重計上を防ぐ |
| STAT-003 | P1 | 学習統計を専用ダッシュボードで確認する | 学習統計を機能タブ内の埋め込み表示ではなく個別ページで提供し、期間を切り替えて主要指標・データベース内の語彙数・登場数・正解数・不正解数・正解率・未登場語数を確認できる。語彙別の学習実績も確認でき、一覧は折りたたみ可能。語彙・学習対象・語義の件数が同一なら重複表示せず、違いがある場合のみ区別を示す |
| STAT-004 | P1 | 語彙別・日付別の学習実績を表とグラフで切り替える | ダッシュボードの語彙別実績と日付別実績に明確な見出しを付け、一覧表とグラフを切り替えて表示できる。グラフは既存の学習統計値を反映し、期間・検索・並べ替えに追従する |
| STAT-005 | P1 | 語彙学習実績の分布を分析する | 語彙数を縦軸とし、自己評価正解率・登場回数・正解数・再学習数の分布を横軸から選択して確認できる。未学習語は正解率の分母から除き、その件数を示す。登場・正解・再学習回数の分布には未学習語を0件として含める |
| STAT-006 | P2 | Track cumulative learning goals | On the dashboard, set and clear overlap-time and distinct-answered-vocabulary targets independently. Show lifetime actuals, remaining amounts, and progress capped at 100%; update from new learning events regardless of the selected date range and preserve targets across reloads. |
| ADD-001 | P2 | 語彙候補を作る | 英文から候補抽出、または語彙リストから候補化できる。英語見出し・日本語の意味・出典を確認して選択登録できる |
| SIM-001 | P2 | 既存・類似候補を除外する | 完全一致とベクトルのコサイン類似度を使う。候補同士も重複判定し、除外理由・一致先・スコアを確認できる。閾値は設定可能で、類似除外は再選択できる |
| LEVEL-001 | P2 | データセットに難易度を付ける | 語義ごとのCEFR推定、根拠、モデル、判定日、手動修正を保持する。未判定を許容し、個人の習熟度と分離する |
| LEVEL-002 | P1 | CEFR難易度を自動で評価する | 未評価の語義をバックグラウンドで自動評価し、進行・失敗・再開を確認できる。手動設定を上書きせず、評価結果と使用量を記録する |
| GEN-001 | P2 | データセットから英文を作る | 対象語彙、難易度、テーマ、長さを指定できる。使われた語彙IDを保持し、指定語の使用を検証して編集・保存できる |
| GEN-002 | P2 | フィルター語彙から重ね読み教材を作る | 教材作成はオーバーラッピング画面内に置き、カテゴリ・方向・習熟状況・難易度等で語彙を絞り込む。選んだ語彙で英文を作り、編集・保存して音声生成とオーバーラッピングへ進める。日本語訳と語義は日本語で生成し、外国語が混入したメモは該当箇所を除去して、教材全体の生成は継続する |
| UI-003 | P1 | React + TypeScriptの機能別タブで操作する | React画面をTypeScript（`.tsx` / `.ts`）で構成し、「オーバーラッピング」「語彙練習」「語彙管理」「語彙追加」「データベース管理」のタブを設けて機能を見つけやすくする |
| OVER-005 | P1 | 文の移動と再生設定を常時操作できる | 設定可能なキーで現在文・前文へ移動し、再生・設定UIを字幕スクロール領域の横に固定表示する。広い画面では本文・操作欄を画面幅に応じて拡張し、狭い画面では横はみ出しを防ぐ |
| OVER-006 | P1 | 再生中の文を字幕領域の先頭に追従表示する | 字幕追従が有効なとき、フォーカス中の文ブロックが切り替わるたびにスクロール領域の先頭へ揃える。同じ文の中では不要なスクロールを起こさない |
| OVER-007 | P1 | 音声と字幕の生成進捗を表示する | 生成中に工程名と約1%刻みの進捗を表示し、完了・失敗を明確にする。APIが正確な完了率を返さない工程では目安であることを示す |
| UI-004 | P1 | 学習画面を見やすくする | 全画面で視覚階層・余白・色・操作部品を統一し、語彙練習では出題語を最も目立たせ、答え・評価操作を明確にする。狭い画面とキーボード操作でも利用できる |
| UX-001 | P1 | 学習者視点でUXを評価し改善する | 主要な学習シナリオをUXの専門的観点でレビューし、根拠・深刻度・改善案を記録する。上位課題をチケット化し、改善後に操作性・アクセシビリティ・E2Eを再評価する |
| OVER-001 | P1 | 既存オーバーラッピングを維持する | 保存教材の再生、字幕追従、速度、繰り返しが利用できる。既存の日本語見出し語データの修復は要求しない |
| OVER-002 | P2 | オーバーラッピングを記録する | 教材ID、再生中の活動時間、日時、セッションを保存し、停止・シーク・繰り返しを考慮して集計する |
| OVER-003 | P1 | 高難度の自然な発声を選べる | 重ね読み用音声で、早口・強い音の連結と弱化・軽いもごもご発音を組み合わせた選択肢を用意する。原文の語と順序を保ち、不自然な誤発音を避けるよう指示する |
| OVER-004 | P1 | 1文単位で重ね読みを繰り返す | 再生中の文または選んだ文だけを反復でき、文頭の0.25秒前から再生し、選択文の終了時刻までの音声サンプルだけを再生する。反復の間に1.5秒の無音を挟む。対象・解除方法が分かり、スペースキーは再生・停止を担う。マウスとキーボードの両方で操作でき、文の時刻情報がない場合は不正確な反復をしない |
| API-001 | P0 | できるだけ最新のOpenAI APIを使う | 実装・更新時に公式資料を確認し、用途別の現行APIとモデルを選定。確認日・根拠URL・採用理由・例外を記録する |
| API-002 | P0 | API処理を管理する | サーバーだけがキーを扱い、用途別モデル設定、使用量、料金、失敗・再試行を管理する。既存教材の再生や語彙学習はAPIなしで動く |

## 統合学習シナリオ: 苦手語彙からオーバーラッピング

ユーザー例: 「カテゴリAの覚えていない語彙上位50件から文章を自動生成してオーバーラッピングする」。

| ID | 優先度 | 要求 | 受け入れ条件 |
|---|---|---|---|
| FLOW-001 | P2 | カテゴリ・習熟状況から教材を作って練習する | オーバーラッピング画面でカテゴリ、学習方向、対象件数（例:50）、難易度、テーマカテゴリを指定し、対象語の確認→英文生成→音声生成→オーバーラッピングへ進める。前回条件を再利用できる |
| SELECT-001 | P2 | 未習得語の順位と選定根拠を示す | 対象方向の学習結果に基づき順位を決め、選出理由を表示する。未学習語を含めるか選択でき、過去N回の出題履歴数と自己評価正答率で絞り込める。同順位でも順序が安定する。対象不足時は実件数を知らせる |
| COVER-001 | P2 | 対象語の使用状況を追跡する | 選定50件と実使用件数を区別し、未使用語・使用箇所を確認できる。50語を収めるための複数教材への分割、未使用語の補完生成ができる |

### 選定・学習上の規則

- カテゴリはデータセットのタグ等に対応づける。既存tags / genre_tagsとの対応は調査して確定する。
- 「覚えていない」の順位は個人の方向別習熟度から算出し、単語のCEFR難易度とは分離する。具体的な算式はT-008で定義・版管理する。
- 既定は未習得語を優先する。未学習語は別の状態として扱い、含める設定を用意する。学習方向不明の旧履歴を特定方向の習得根拠にしない。
- 50件は選ぶ語彙数であり、文章の単語数ではない。自然な文章に収まらない場合は複数の短い教材へ分け、一つの練習セットとして扱う。
- 対象語彙・語義ID、選定時の順位と条件、実際の使用箇所、生成された教材との対応を保存する。語形変化の許容規則はT-011で定義する。
- 文章や音声に触れたことを語彙の習得・正答に自動変換しない。練習した語を後で語彙学習に回せるようにする。
- 開始前に生成する教材数とAPI料金の目安を示し、途中失敗から再開できる。

## 全機能の完了確認

- 要求IDと実装チケットが対応している。
- 正常操作、空データ、不正入力、保存失敗を確認する。API機能は通信失敗と再試行も確認する。
- 学習画面はマウス操作とキーボード操作の両方を確認する。
- APIを使う一括処理は対象件数と料金の目安を開始前に示し、中断・再開時に完了済み項目を重複処理しない。
- 実際に確認した内容と未確認事項をチケットに記録する。

## テスト受け入れ条件

- **TEST-001 (P0):** 各実装チケットに変更対象に応じたテスト計画・結果・実行コマンド・テストデータを記録する。統合テストは機能変更に必須、E2Eは画面を通るユーザーシナリオに必須とし、未実施なら理由を書く。
- チケットごとに、変更に対応する自動テスト（単体・統合・E2Eの該当範囲）を実行し、コマンドと結果をチケットへ記録する。機能チケットでは統合テストを必須とし、利用者の画面操作に関わるチケットではE2Eテストも必須とする。
- その層が適用されない場合は理由を記録する。テスト未実行、失敗、または未確認の受け入れ条件があるチケットを完了にしない。
- テストは固定データセットを使用し、実データの更新やOpenAI APIへの課金を避ける。外部APIは既定で差し替え可能にする。

## UI-006: Collapsible page sections

Major content sections on feature pages can be expanded and collapsed independently using an accessible heading control. The sections start expanded by default; vocabulary management exposes vocabulary, saved-material, and CEFR assessment areas separately.

## Saved materials: SQLite is canonical

- **DATA-006:** Deleting a saved material removes its database record and vocabulary links, preserves vocabulary/history, and safely removes only unshared audio artifacts. Legacy subtitle JSON remains as a migration artifact and is not deleted automatically.
- **DATA-007:** Explicit AI summary generation reads the material text from SQLite and saves title, summary, model, prompt version, and generation time in SQLite. Listing/details do not call the API; editing text invalidates stale summaries.
- **DATA-008:** The vocabulary-management and overlap material lists use the same SQLite records, counts, and order. DB-only materials are included. Subtitle/timing payloads are loaded from SQLite by material ID; audio binaries remain in the configured audio directory.
- **DATA-009:** The overlap saved-material details show the AI summary as the only description, distinguish materials without a generated summary, and retain other useful metadata without making an API call.
- **DATA-010:** Existing subtitle JSON is imported once, transactionally per file, into SQLite after the schema migration backup. The import ledger records the source name and digest; repeat reads never re-import or overwrite DB state. Invalid files remain and surface as warnings. Newly generated materials write structured content only to SQLite and create audio binaries only.