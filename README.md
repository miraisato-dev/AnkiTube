# AnkiTube
YouTube字幕からAnki用カードを自動生成するツール
<img src="https://github.com/user-attachments/assets/14a4aa17-3169-43c5-9c2f-04a6485a100e" alt="Home Page Demo" width="100%" max-width="800px" />

## 主な機能
- **YouTube動画の解析**: URLを入力するだけで、動画情報と字幕を取得
- **インタラクティブな編集（Editor）**: 取得した字幕を確認・編集しながら、AIがカードの元となるデータを抽出
- **Anki形式エクスポート（Output）**: 生成されたカードを、Ankiに直接インポートできる形式で出力
- **履歴管理（History）**: 過去に生成した動画やカードのログをいつでも確認・再利用可能

### デモ（GIF）
### ホーム画面
<img width="1080" height="608" alt="home_gif" src="https://github.com/user-attachments/assets/4a5d2060-8c27-4110-871a-002a25c7a443" />
### 編集、出力画面
<img width="1080" height="608" alt="edit_gif" src="https://github.com/user-attachments/assets/e5694dcd-b11e-4308-8268-ab42fe21b954" />
### 履歴画面
<img width="720" height="405" alt="history_gif" src="https://github.com/user-attachments/assets/ac50caac-dbbd-436d-b7e5-5a4200fefb63" />

## 技術スタック
- **Backend**: Python, Flask
- **Database**: SQLite (SQLAlchemy / Flask-Migrate)
- **Frontend**: HTML, TailwindCSS, JavaScript (Templates)

### このアプリを動かすための最初のコマンド
## 🚀 はじめに（セットアップ）

### 1. リポジトリのクローンと準備
```bash
git clone [https://github.com/あなたのユーザー名/AnkiTube.git](https://github.com/あなたのユーザー名/AnkiTube.git)
cd AnkiTube
# 必要に応じて仮想環境の作成やライブラリのインストール手順をここに記載
# 例: pip install -r requirements.txt

### 2. データベースの初期化と反映
1. flask db init: 管理リポジトリの初期化。
2. flask db migrate -m "Initial migration": モデル定義からの変更検知と指示書の自動生成。
3. flask db upgrade: 実際のデータベースファイルへの反映。
以上によりテーブルが作成される

### 3. アプリケーションの起動
flask run
# または python app.py など、お使いの起動コマンド

### ディレクトリ構成
- app.py          # アプリのメインプログラム（Flask/DB設定・ルーティング）
- models.py       # データベースのテーブル定義（Video, Subtitle, AICards）
- functions.py    # YouTube APIや字幕処理などのロジック（予定）
- data.sqlite     # 生成されたデータベースファイル
- migrations/     # DBの変更履歴（Flask-Migrateが生成）
- templates/      # HTMLファイル
- static/         # CSS/JSファイル

### APIキーの設定方法
.envファイルを用意し、以下にAPIキーを記述
- YouTube Data API v3
- Google AI Studio Gemini API
YOUTUBE_API_KEY=あなたのYouTube_Data_API_v3キー
GEMINI_API_KEY=あなたのGemini_API_キー


### 今後つけたい機能
- 絞り込み検索(履歴画面＋編集画面)
  - 難易度、
- パーソナライズ
  - ユーザー個人の英語力やどこまで伸ばしたいかに合わせてAIプロンプトを変更
- 音声、イメージ画像などもカードに追加したい
  - その際はAICardテーブルのai_dataカラムに追加すること(dict)




