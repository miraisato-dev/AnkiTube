graph TD
    %% 画面（ノード）の定義
    Home[<b>Home 画面</b><br/>URL入力 / 新規受付]
    History[<b>History 画面</b><br/>過去の動画タイトル一覧]
    Editor[<b>Editor 画面</b><br/>動画再生 / 字幕編集 / AI再解析]
    Output[<b>Output 画面</b><br/>Anki用CSVダウンロード / 完了]
    
    %% 処理の定義
    API_Get[YouTube API<br/>字幕・タイトル取得]
    API_AI[AI 解析<br/>重要度判定 / 翻訳]

    %% 遷移の流れ
    Home -- "1. URLを入力して送信" --> API_Get
    API_Get -- "2. データ取得完了" --> API_AI
    API_AI -- "3. DB保存して自動遷移" --> Editor

    History -- "過去の動画を再開" --> Editor

    subgraph "Editor内での詳細アクション"
        Editor -- "AI設定変更 & 再実行" --> API_AI
        Editor -- "編集を一時保存" --> Editor
    end

    Editor -- "エクスポート実行" --> Output
    
    %% ナビゲーション（共通メニュー）からの遷移
    NavHome((Nav: Home)) -.-> Home
    NavHist((Nav: History)) -.-> History
    
    %% スタイル設定
    style Home fill:#dae2ff,stroke:#003d9b,stroke-width:2px
    style Editor fill:#dae2ff,stroke:#003d9b,stroke-width:2px
    style History fill:#f3f4f6,stroke:#737685
    style Output fill:#adecff,stroke:#004e5d
    style API_AI fill:#ffdea8,stroke:#7c5800,stroke-dasharray: 5 5