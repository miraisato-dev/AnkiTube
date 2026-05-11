# AnkiTube
YouTube字幕からAnki用カードを自動生成するツール


### このアプリを動かすための最初のコマンド
1. flask db init: 管理リポジトリの初期化。
2. flask db migrate -m "Initial migration": モデル定義からの変更検知と指示書の自動生成。
3. flask db upgrade: 実際のデータベースファイルへの反映。

以上によりテーブルが作成される

### ディレクトリ構成
- app.py          # アプリのメインプログラム（Flask/DB設定・ルーティング）
- models.py       # データベースのテーブル定義（Video, Subtitle）
- functions.py    # YouTube APIや字幕処理などのロジック（予定）
- data.sqlite     # 生成されたデータベースファイル
- migrations/     # DBの変更履歴（Flask-Migrateが生成）
- templates/      # HTMLファイル
- static/         # CSS/JSファイル
