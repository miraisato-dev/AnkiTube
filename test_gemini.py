import os
from dotenv import load_dotenv
from google import genai

# .env ファイルを読み込む
load_dotenv()

# .env の中に書かれている変数名に合わせて取得
api_key = os.environ.get("GEMINI_API_KEY")

print(f"--- [DEBUG] 取得できたAPIキー: {api_key[:10] if api_key else 'None'}... ---")

if not api_key:
    print("❌ エラー: .env から APIキー が読み込めていません！ファイル名や記述を確認してください。")
else:
    try:
        print("🤖 Geminiに接続テスト中...")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash', # 現在の標準モデル
            contents='「こんにちは」とだけ返事してください。'
        )
        print(f"✨ Geminiからの返答: {response.text}")
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")