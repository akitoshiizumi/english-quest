# 初回起動用データベース

`manifest.json` と `vocab.db.part-*.gz` が、配布用SQLiteデータベースです。
各ファイルは通常のGitファイルで、Git LFSや別途ダウンロードは不要です。
`py server.py` または `start_windows.bat` の初回起動で検証・展開します。
すでに `dataset/vocab.db` が存在するときは上書きしません。
ベクトル値は768次元に正規化し、小数点以下4桁で保存します。
復元には約140MBの空き容量が追加で必要です。

データを更新する場合は、アプリを停止し、別の出力先へ作成してから
既存バンドルと置き換えます。

```powershell
py tools/package_starter_data.py --output dataset/starter-new
```

元データをSQLite Backup APIでコピーするため、元のデータベースを変更しません。
バンドルは語彙・教材に加え、作成元データベースの学習履歴と設定も含みます。
