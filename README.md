# AnkiTube
YouTube字幕からAnki用カードを自動生成するツール
<img src="https://github.com/user-attachments/assets/14a4aa17-3169-43c5-9c2f-04a6485a100e" alt="Home Page Demo" width="100%" max-width="800px" />



### このアプリを動かすための最初のコマンド
1. flask db init: 管理リポジトリの初期化。
2. flask db migrate -m "Initial migration": モデル定義からの変更検知と指示書の自動生成。
3. flask db upgrade: 実際のデータベースファイルへの反映。

以上によりテーブルが作成される

### ディレクトリ構成
- app.py          # アプリのメインプログラム（Flask/DB設定・ルーティング）
- models.py       # データベースのテーブル定義（Video, Subtitle, AICards）
- functions.py    # YouTube APIや字幕処理などのロジック（予定）
- data.sqlite     # 生成されたデータベースファイル
- migrations/     # DBの変更履歴（Flask-Migrateが生成）
- templates/      # HTMLファイル
- static/         # CSS/JSファイル

### GIF
home画面
<img width="1080" height="608" alt="home_gif" src="https://github.com/user-attachments/assets/4a5d2060-8c27-4110-871a-002a25c7a443" />


editor画面とoutput画面
<img width="1080" height="608" alt="edit_gif" src="https://github.com/user-attachments/assets/e5694dcd-b11e-4308-8268-ab42fe21b954" />


history画面

<img width="720" height="405" alt="history_gif" src="https://github.com/user-attachments/assets/ac50caac-dbbd-436d-b7e5-5a4200fefb63" />








