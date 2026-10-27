# チケット一覧

新しいチケットは [`TEMPLATE.md`](TEMPLATE.md) をコピーして作成します。各受け入れ条件を確認可能な結果として書き、適用するテスト層とfixtureをチケット単位で定めてください。

状態は未着手 / 作業中 / 確認待ち / 完了。未完了チケットはこの一覧に置き、完了したチケット本文は [`done/`](done/) へ移動します。完了時は状態とリンク・変更履歴も更新します。テスト方針は[テスト方針](../testing.md)を参照してください。

## 未完了

| ID | 内容 | 優先度 | 依存 | 状態 |
|---|---|---|---|---|
| [T-074](T-074.md) | Show saved material creation timestamps | P2 | T-073 | 作業中 |
| [T-073](T-073.md) | Make SQLite the sole source of truth for saved materials | P1 | T-071, T-072 | 作業中 |
完了チケットは[done/](done/README.md)に移動します。
| [T-072](done/T-072.md) | Make saved JSON authoritative for title and AI summary | P1 | T-061, T-063, T-071 | 完了 |
