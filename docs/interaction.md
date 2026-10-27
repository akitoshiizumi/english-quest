# 操作仕様

## 語彙学習

| 状態 | A / U | S / I | 画面ボタン |
|---|---|---|---|
| 問題表示 | 答えを表示 | 答えを表示 | 答えを表示 |
| 答え表示 | もう一度 | 覚えていた | もう一度、覚えていた |

キーの意味は画面の状態で決まる。問題表示中に評価は記録しない。評価後に次問へ進む。同じ語でも日→英と英→日の習熟度を分ける。方式は自己評価であり、自動採点ではない。

## 実装契約

- 操作IDを reveal_answer / rate_again / rate_known とし、ボタンとキーは共通の操作処理を呼ぶ。
- 設定は「操作ID → キー配列」。初期値は reveal_answer=[a,u,s,i]、rate_again=[a,u]、rate_known=[s,i]。有効な状態が異なる割り当ては競合としない。
- 英字は大文字・小文字を同一扱いとする。Ctrl/Alt/Meta付き、IME変換中、入力欄・編集可能要素・設定ダイアログでは学習キーを発火させない。
- keydownのrepeatを無視し、押し続けたキーが答え表示後の評価にならないよう、キーを離すまで同一操作を再受付しない。遷移中・保存中は重複操作を受け付けない。
- ボタンに現在の割り当てを表示する。Enter/Spaceによる標準ボタン操作、Tab移動、フォーカス表示も保つ。
- 設定画面では複数割り当て、解除、既定値への復元を行える。主要操作にキーがない場合は知らせる。
- 同じ状態で別の操作に同じキーを割り当てた設定は保存しない。

## 画面構成案

画面はReactで構築し、上部またはサイドに次の機能タブを置く。

- オーバーラッピング
- 語彙練習
- 語彙管理（閲覧・編集）
- 語彙追加
- データベース管理

語彙練習タブには語彙学習用のカテゴリ・方向・習熟状況・CEFR等の条件を置く。オーバーラッピングタブには「フィルタした語彙で重ね読み用英文を作成」を置き、教材用フィルター、対象語確認、英文生成・保存から音声生成へ続けられるようにする。教材作成だけの独立タブは作らない。学習統計では語彙練習時間とオーバーラッピング時間を別項目として確認できる。日常の学習開始にモデル選択やデータベース管理を要求しない。

重ね読みの1文反復は、各文の「この文を繰り返す」ボタンか設定キー（初期値 R）で開始・解除する。R は再生位置の文を対象とし、別の文のボタンで対象を切り替える。A キー（設定可能）は再生位置の文頭へ戻って1回再生し、W キー（設定可能）は1つ前の文頭へ戻って1回再生する。W が第1文で押された場合は第1文頭から再生する。反復中の文を明示し、全文の繰り返しより優先する。入力欄・選択欄の操作中、IME変換中、修飾キー併用時はこれらのキー操作を発火させない。単語時刻がない教材では文の境界を推測せず、該当操作を無効にして理由を示す。再生コントロールと音声設定は、長い字幕をスクロールしても横に固定表示する。

1文反復では、文の終わりで音声を止め、1.5秒の無音後に同じ文を再生する。再生位置は文頭の0.25秒前（音声先頭より前には戻さない）にする。無音中にスペースキーを押した場合は予定された再生を停止し、再度押したときに同じ位置から再開する。文ボタンにフォーカスがあってもスペースキーは再生・停止に割り当て、文の開始・解除は Enter または R を使う。

1文反復は、文頭の0.25秒前から最終単語の終了時刻までの音声サンプルだけを切り出して再生する。次文の開始時刻がそれより早い場合は次文開始時刻で切る。停止後に再生位置を監視して一時停止する方式や0.15秒の補正は使わない。切り出す範囲が短すぎる文は反復不可とする。単語時刻自体が実音声とずれた教材では、必要に応じて時刻情報の修正が要る。

語彙管理一覧は1ページ50行とし、列見出しからソートできる。検索・絞り込み後もページ移動時に条件を維持し、現在の表示範囲と該当件数を示す。ページ番号欄にページを入力してEnterでも移動でき、範囲外は先頭または末尾へ丸める。学習統計は独立したダッシュボードページで提供する。

「フィルタした語彙で重ね読み用英文を作成」では、語彙を選ぶカテゴリフィルターと教材テーマを別に指定できる。テーマはデータセットのカテゴリ一覧から選ぶ。過去N回の出題履歴数、直近N回の自己評価正答率上限、N回未満の履歴を含めるかを語彙練習と同じ意味で設定し、プランに合う対象語だけを選ぶ。正答率上限を使う場合はNも必須。教材作成で「N回未満の履歴を含める」を選んだ場合、回答履歴が0件の語も含める。回答履歴がない語の正答率は未定義のため、正答率上限では除外しない。

ダッシュボードの「語彙別の学習実績（全期間）」は折りたたみ可能とし、初期状態は閉じる。登録語彙・アーカイブを除く学習対象・語義の件数がすべて同じ場合は「語彙」1件にまとめる。値が異なる場合は、違いの理由が分かるラベルを表示する。

語彙別と日付ごとの学習実績には「一覧／グラフ」の切替を設け、セクション見出しを常に表示する。語彙グラフは検索・並べ替え後の同じ行を使い、正解数・再学習数と正解率を表示する。日付グラフは回答数（正解・再学習）と、語彙練習・オーバーラッピングの学習時間を選択できる。期間切替後も選んだ表示モードを保ち、空データ時は案内を表示する。切替はキーボードで操作でき、一覧表示にも切替で戻れる。

語彙別実績には分布分析を設ける。横軸の指標を自己評価正解率・登場回数・正解数・再学習数から選び、縦軸は該当語彙数とする。正解率分布は評価済みの語だけを対象とし、未学習語数を別に明示する。件数系の分布は未学習語も0件の語彙として含める。語彙検索に応じて分析対象を絞り込む。

累計学習目標はオーバーラッピングの活動時間（時間）と、1回以上回答した異なる語彙数を個別に設定する。ダッシュボードの期間選択には連動せず、実績・目標・残り・達成率をそれぞれ表示する。進捗率は100%で上限表示し、目標超過後も実績数を表示する。目標欄を空にして保存すると、その目標を解除する。目標未設定時も現在の累計と未設定状態を示す。

保存済み教材には個別の削除操作を置き、実行前に教材名と削除対象を確認する。キャンセルはデータを変更しない。確定後は教材と教材・語彙の関連を削除し、語彙本体と学習履歴は保持する。教材に紐づく音声・字幕は現在の教材保存先内にあり、他教材から参照されていない場合だけ削除する。

語彙練習では条件設定と出題カードを分け、出題語を大きく表示する。回答は答え表示後に評価ボタン（A/U、S/I）を利用し、キーボード・マウスのどちらでも同じ操作となる。モバイルでは入力条件を2列に配置し、出題語カードは画面幅を超えない。


In the saved materials list, show each AI summary below its title. For materials without one, show that no summary exists yet. Generate or regenerate only after an explicit button click; disclose that OpenAI API charges apply and that merely opening the list makes no API call. If the title or text changes, invalidate the old summary. On missing credentials or generation errors, explain the failure and preserve existing metadata.

Saved-material counts (T-062): show the complete database material list in both the overlap selector and vocabulary-management table, independent of the vocabulary search field. The selector labels text-only materials as lacking audio, loads their text into the editor, and disables audio transport controls.

When a saved material is selected in the overlap screen, show its AI-generated summary and an explicit not-yet-generated state in the metadata panel. Only show `metadata.summary` as an AI summary when its provenance (`summary_model`) is present. Opening material details must not trigger summary generation or any API call.


## Vocabulary practice focus mode (T-065)

The focus toggle is available in the practice heading. While active, the page hides global navigation, page actions, other panels, and practice configuration, leaving the prompt stage, answer/rating controls, progress, status, and an exit button. Escape and the exit button restore the regular page. Focus mode is not persisted and does not reset the current question or phase.
