# funciton.py (関数を入れておくファイル)
# 正規表現（Regular Expression）を使って高度な文字列の検索、置換、分割、マッチングを行うための標準ライブラリ（モジュール）
import re
import os
import io
import csv
import json
import requests

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv
import google.generativeai as genai

from models import Video, Subtitle, SubtitleAnalyses, AICard

# .envファイルを読み込む
load_dotenv()

# .envファイル内の環境変数からAPIキーを取得
API_KEY = os.getenv("YOUTUBE_DATA_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = 'gemini-3.1-flash-lite'

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

# ==========================================================
# 補助関数：YouTube自動字幕特有の[Music]などのノイズを安全に消去
# ==========================================================
def clean_subtitle_text(text):
    """[Music] や (Laughter) などの不要なト書きノイズを消去"""
    if not text:
        return ""
    
    pattern = r'\[.*?\]|\(.*?\)|［.*?］|（.*?）'
    cleaned = re.sub(pattern, '', text, flags=re.IGNORECASE)
    return cleaned.strip()

# ===============================
# # A Youtubeから取得した字幕と動画情報をDBに保存
# ===============================
def get_video_id(url):
    """URLから11桁のビデオIDを抽出"""

    patterns = [
        r"v=([0-9A-Za-z_-]{11})",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"embed/([0-9A-Za-z_-]{11})"
    ]
    for p in patterns:
        match = re.search(p, url)
        if match:
            return match.group(1)
    return None

def parse_duration(iso_duration: str) -> str:
    """PT12M45S → '12:45'"""
    if not iso_duration:
        return '??:??'
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
    if not match:
        return '??:??'
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

def get_video_metadata(video_id):
    """動画のメタデータをYouTube Data V3 APIから取得"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,contentDetails",
        "id": video_id,
        "key": API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return None
        
        item = data["items"][0]
        snippet = item["snippet"]
        content = item["contentDetails"]

        # 呼び出し元が使いやすい形でdictを返す
        return {
            "video_id": video_id,
            "title": snippet.get("title"),
            "channel_name": snippet.get("channelTitle"),
            "summary": snippet.get("description"),
            "duration": content.get("duration"), 
            "published_at": snippet.get("publishedAt")
        }

    except Exception as e:
        print(f"Error fetching metadata: {e}") # 原因究明用ログ
        return None


def fetch_subtitles(video_id):
    """字幕データのみをYouTubeTranscriptAPIから取得"""
    try:
        api = YouTubeTranscriptApi()
        # アメリカ英語(en-US)、イギリス英語(en-GB)なども網羅した言語リストを渡す
        fetched = api.fetch(
            video_id, 
            languages=['en', 'en-US', 'en-GB', 'ja']
        )
        if fetched:
            print(f"--- [DEBUG] 字幕の取得に完全成功しました！ (行数: {len(fetched)}) ---")
            return fetched
            
    except Exception as e:
        print(f"--- [DEBUG] 字幕取得エラー (ID: {video_id}): {e} ---")
        return None


def combine_subtitles_to_sentences(raw_subtitles):
    """細切れの字幕データを意味のある1文単位に結合"""
    combined_sentences = []
    current_text = []
    current_start = None
    current_duration = 0.0
    sequence_counter = 0

    for item in raw_subtitles:
        if isinstance(item, dict):
            text = item.get("text", "").strip()
            start = item.get("start", 0.0)
            duration = item.get("duration", 0.0)
        else:
            text = (
                getattr(item, "text", "").strip()
                if hasattr(item, "text")
                else item.get("text", "").strip()
            )
            start = (
                getattr(item, "start", 0.0)
                if hasattr(item, "start")
                else item.get("start", 0.0)
            )
            duration = (
                getattr(item, "duration", 0.0)
                if hasattr(item, "duration")
                else item.get("duration", 0.0)
            )

        # 最初の要素の開始時間を記録
        if current_start is None:
            current_start = start

        current_text.append(text)
        current_duration += duration

        # 2. 文末（. や ? や !）で終わっているか、または次の文字がパッと切れているか判定
        is_end_of_sentence = False
        if re.search(r'[.!?]$', text):
            is_end_of_sentence = True
        elif len(text) > 0 and text[-1] in ['"', "'", "」", "』"]: # 閉じカッコ対応
            is_end_of_sentence = True
        
        # 自動生成字幕対策：1文の継続時間が15秒を超えたら、記号がなくても一旦区切る
        elif current_duration > 15.0:
            is_end_of_sentence = True

        # 確定処理
        if is_end_of_sentence:
            # 溜まった単語をスペースで繋ぐ（Yeah. や Oh, なども1文として扱う）
            full_sentence = re.sub(r'\s+', ' ', " ".join(current_text)).strip()
            combined_sentences.append({
                "sequence": sequence_counter,
                "start_time": current_start,
                "duration": round(current_duration, 2),
                "raw_text": full_sentence
            })
            
            # カウンターを進めて、一時変数をリセット
            sequence_counter += 1
            current_text = []
            current_start = None
            current_duration = 0.0

    # ループが終わってもまだお尻に文字が残っていた場合の救済処理
    if current_text:
        full_sentence = " ".join(current_text)
        full_sentence = re.sub(r'\s+', ' ', full_sentence).strip()
        combined_sentences.append({
            "sequence": sequence_counter,
            "start_time": current_start if current_start is not None else 0.0,
            "duration": current_duration,
            "raw_text": full_sentence
        })

    print(f"--- [DEBUG] 結合完了: {len(raw_subtitles)}件 の細切れ字幕を {len(combined_sentences)}件 の綺麗な文に合体しました ---")
    return combined_sentences


def save_metadata_and_subtitles(metadata, fetched):
    """A.5 字幕と動画情報をDBに保存"""
    from app import db # 循環参照対策

    print("=== [DEBUG] save_metadata_and_subtitles が呼び出されました ===")
    print(f"=== [DEBUG] fetched の型: {type(fetched)}, 中身の数: {len(fetched) if fetched else 0} ===")

    try:
        # 重複チェック
        print("=== [DEBUG] 1. 重複チェックを開始します ===")
        existing_video = db.session.get(Video, metadata["video_id"])
        if existing_video:
            print("=== [DEBUG] 動画はすでにDBに存在します ===")
            return False
        
        # Video保存
        print("=== [DEBUG] 2. Videoレコードを作成します ===")
        new_video = Video(
            video_id=metadata["video_id"],
            title=metadata["title"],
            channel_name=metadata["channel_name"],
            summary=metadata.get("summary"),
            duration=parse_duration(metadata.get("duration"))
        )

        db.session.add(new_video)

        # 一旦 flush して、DBに「親がいる状態」を認識させる
        print("=== [DEBUG] 3. db.session.flush() を実行します ===")
        db.session.flush()

        # 細切れ字幕を結合処理する関数combine_subtitle_to_sentenceを呼び出す
        print("=== [DEBUG] 3.5 細切れ字幕の結合処理を実行します ===")
        combined_fetched = combine_subtitles_to_sentences(fetched)

        # Subtitle保存
        print("=== [DEBUG] 4. 字幕のループ処理に入ります ===")
        subtitle_objects = []

        # 結合済みのリスト (combined_fetched) をループするように変更
        for s in combined_fetched:
            # combine_subtitles_to_sentences から返るデータは必ず辞書形式です
            sequence = s.get('sequence', 0)
            start_time = s.get('start_time', 0.0)
            raw_text = s.get('raw_text', '')
            # [Music] などのノイズ除去をここでも適用（保険として）
            cleaned_text = clean_subtitle_text(raw_text)
            # テキストが空っぽ（[Music]だけで構成されていた文など）ならスキップ
            if not cleaned_text.strip():
                continue
            sub = Subtitle(
                video_id=metadata["video_id"],
                sequence=sequence,
                start_time=start_time,
                raw_text=cleaned_text,
                is_selected=False
            )
            subtitle_objects.append(sub)

        print(f"=== [DEBUG] 5. bulk_save_objects を実行します（件数: {len(subtitle_objects)}件） ===")
        db.session.bulk_save_objects(subtitle_objects)

        print("=== [DEBUG] 6. db.session.commit() を実行します ===")
        db.session.commit()
        print("Successfully saved original subtitles to Database.")
        return True

    except Exception as e:
        db.session.rollback()
        print("=== [DEBUG] 致命的なエラーが発生しました！ ===")
        print(f"エラー内容: {e}")
        import traceback
        traceback.print_exc() # エラーの発生源を詳しく表示
        return False


# ===============================
# B. Geminiによる「重要度分析」
# ===============================

def analyze_subtitles_with_gemini(subtitles_json_data):
    """B.1 字幕リストを20行ずつのチャンクに分割し、Geminiで重要度分析と翻訳を行う"""
    # 1. 渡されたデータが文字列(JSON)ならPythonのリストに復元
    if isinstance(subtitles_json_data, str):
        try:
            subtitles_list = json.loads(subtitles_json_data)
        except Exception as e:
            print(f"入力データのパースに失敗しました: {e}")
            return None
    else:
        subtitles_list = subtitles_json_data

    # 結果を格納するコンテナ
    all_analyzed_subtitles = []
    all_recommendations = []
    detected_difficulty = "B2" # デフォルト値

    # トークン制限対策：20行ずつの「束（チャンク）」に分割してループ処理
    chunk_size = 20
    total_subtitles = len(subtitles_list)
    print(f"=== Gemini解析スタート (全 {total_subtitles} 行を {chunk_size} 行ずつ処理します) ===")

    for i in range(0, total_subtitles, chunk_size):
        chunk = subtitles_list[i : i + chunk_size]
        print(f" チャンク処理中: {i+1}行目 〜 {min(i+chunk_size, total_subtitles)}行目...")

        SYSTEM_PROMPT = f"""
        あなたは非常に優秀な英語教師であり、言語学者、そしてプロの翻訳家です。
        提供されたYouTubeの英語字幕リスト（JSON）を分析し、以下のタスクを行ってください。

        【タスク】
        1. 【各行（1文単位）への自然な日本語訳の作成】
            - 提供された `sequence` の英文に対して、自然で美しい日本語訳を作成し、`ja_translation` に格納してください。
            - 入力された `sequence` の行数と、出力する `analyzed_subtitles` の行数は必ず「完全に一致」させてください。

        2. 【重要表現の厳選】
            - 日常会話やビジネス、テスト（TOEIC等）で頻繁に使用される重要な単語や熟語を、このチャンクデータから最大5件まで厳選し、解説を加えて `recommendations` に格納してください。
            - その重要表現が「どの `sequence` 番号の行から抽出されたか」を必ず指定してください。

        3. 【難易度の判断】
            - この動画全体の英語レベル（A1〜C2の6段階）を判定し、`difficulty_level` に格納してください。

        【出力形式】
        必ず以下のJSONオブジェクト形式のみで出力してください。
        {{
            "difficulty_level": "A1"から"C2"のいずれか,
            "recommendations": [
                {{
                    "sequence": 対応する元の字幕のsequence番号,
                    "importance_score": 0.0から10.0の数値,
                    "target_term": "抽出された具体的な単語や熟語",
                    "ai_summary": "日本語による短い解説（30文字以内）。",
                    "category": "word" または "idiom" または "sentence"
                }}
            ],
            "analyzed_subtitles": [
                {{
                    "sequence": 対応する元の字幕のsequence番号,
                    "ja_translation": "その行（1文）に対する自然な日本語訳"
                }}
            ]
        }}
        """

        final_prompt = f"{SYSTEM_PROMPT}\n\n【分析対象のデータ（チャンク分）】\n{json.dumps(chunk, ensure_ascii=False)}"

        try:
            # generation_config で JSON 出力を絶対強制（MIMEタイプ指定）
            response = model.generate_content(
                final_prompt,
                generation_config={"response_mime_type": "application/json"}
            )

            # APIの強制JSONモードのおかげで、100%安全にjson.loadsが通ります
            chunk_results = json.loads(response.text.strip())

            # 難易度を更新
            if "difficulty_level" in chunk_results:
                detected_difficulty = chunk_results["difficulty_level"]

            # 各パーツを全体のコンテナに統合
            if "analyzed_subtitles" in chunk_results:
                all_analyzed_subtitles.extend(chunk_results["analyzed_subtitles"])
            
            if "recommendations" in chunk_results:
                all_recommendations.extend(chunk_results["recommendations"])

        except Exception as e:
            print(f"チャンク ({i}〜) の解析中にエラーが発生しました。この行はスキップします。 エラー: {e}")
            # 万が一のクラッシュ防止：スキップした行の最低限の器だけ作っておく
            for item in chunk:
                all_analyzed_subtitles.append({
                    "sequence": item.get("sequence"),
                    "ja_translation": item.get("ja_translation", "（翻訳エラーのためスキップされました）")
                })
            continue

    # 2. 全チャンク統合後、重要度（importance_score）順に全体をソート
    try:
        sorted_recommendations = sorted(
            all_recommendations,
            key=lambda x: float(x.get('importance_score', 0)) if x.get('importance_score') is not None else 0.0, 
            reverse=True
        )
        # 30件以内に制限（全体のルール遵守）
        sorted_recommendations = sorted_recommendations[:30]
    except Exception as e:
        print(f"ソート処理中にエラー（デフォルト順のままにします）: {e}")
        sorted_recommendations = all_recommendations[:30]

    print(f"--- 全チャンク分析完了 (総合Level: {detected_difficulty}) ---")

    # 3. 元のシステムが期待する辞書形式に整形して返却
    return {
        "difficulty_level": detected_difficulty,
        "recommendations": sorted_recommendations,
        "analyzed_subtitles": all_analyzed_subtitles
    }


def save_importance_analysis(subtitles_from_db, analysis_results):
    """ B.2 AIの分析結果（翻訳・重要度スコア）をDBに保存"""
    # 循環参照対策
    from app import db

    print("--- Starting save_importance_analysis (SEQUENCE MATCHING MODEL) ---")

    MODEL_NAME = "gemini-3.1-flash-lite"

    # もし分析結果自体が空なら早期リターン
    if not analysis_results:
        print("[ERROR] analysis_results が空のため保存をスキップします。")
        return

    # 1. Geminiのデータを安全に取得（新プロンプトのキー名に対応）
    raw_subtitles = analysis_results.get("analyzed_subtitles", [])
    raw_recs = analysis_results.get("recommendations", [])

    # sequence番号をキーにした辞書に変換して、一瞬で検索できるようにする
    analyzed_dict = {item.get("sequence"): item for item in raw_subtitles if item and "sequence" in item}
    recs_dict = {item.get("sequence"): item for item in raw_recs if item and "sequence" in item}

    print(f"Mapping AI data onto {len(subtitles_from_db)} original database records...")

    # 事前に既存の解析レコードを全件一括取得して辞書化（SQL発行を1回にして高速化）
    target_sub_ids = [getattr(s, 'id', getattr(s, 'subtitle_id', None)) for s in subtitles_from_db]
    target_sub_ids = [tid for tid in target_sub_ids if tid]
    
    existing_records = {
        r.subtitle_id: r for r in db.session.query(SubtitleAnalyses).filter(
            SubtitleAnalyses.subtitle_id.in_(target_sub_ids)
        ).all()
    }

    # 2. メインループ
    for s in subtitles_from_db:
        target_sub_id = getattr(s, 'id', getattr(s, 'subtitle_id', None))
        current_seq = s.sequence  # DB側のsequence番号を取得

        if not target_sub_id or current_seq is None:
            continue

        # --- sequence番号をフックに、Geminiデータからピンポイント抽出 ---
        matched_subtitle = analyzed_dict.get(current_seq)
        matched_rec = recs_dict.get(current_seq)

        # 翻訳の抽出（見つからなければ空文字）
        final_translation = matched_subtitle.get('ja_translation', '') if matched_subtitle else ''

        # レコードの取得または新規作成
        analysis_record = existing_records.get(target_sub_id)
        if not analysis_record:
            analysis_record = SubtitleAnalyses(
                subtitle_id=target_sub_id,
                ai_model_name=MODEL_NAME,
                prompt_version="v5.0_sentence_combined"
            )
            db.session.add(analysis_record)

        # データの流し込み
        analysis_record.ja_translation = final_translation

        # 重要表現（単語解説など）があれば格納
        if matched_rec:
            try:
                final_score = float(matched_rec.get('importance_score', 7.0))
            except (ValueError, TypeError):
                final_score = 7.0

            analysis_record.importance_score = final_score
            analysis_record.target_term = matched_rec.get('target_term')
            analysis_record.ai_summary = matched_rec.get('ai_summary')
            analysis_record.category = matched_rec.get('category', 'word')
        else:
            analysis_record.importance_score = 0.0
            analysis_record.target_term = None
            analysis_record.ai_summary = None
            analysis_record.category = "sentence"

    # 3. 最後に一括でコミット
    try:
        db.session.commit()
        print("--- AI Analysis fixed successfully! [SEQUENCE MATCHED] ---")
    except Exception as e:
        db.session.rollback()
        print(f"Database commit failed: {e}")


# =======================================================
# C ユーザー選択
# =======================================================
def update_status(subtitle_id: int, status: int):
    """ B.3 字幕の選択状態を更新"""
    from app import db # 循環参照対策

    subtitle = db.session.get(Subtitle, subtitle_id)
    
    if not subtitle:
        raise ValueError(f"ID {subtitle_id} の字幕が見つかりません。")
    
    try:
        # status (0 or 1) をそのまま、またはBoolean型に変換して代入
        subtitle.is_selected = status
        db.session.commit()
        return "Success"
        
    except SQLAlchemyError as e:
        # 例外処理: DBエラー → rollback
        db.session.rollback()
        print(f"データベースエラーが発生しました: {e}")
        raise e

# =======================================================
# D カード生成フェーズ
# =======================================================
def get_selected_subtitles(subtitle_ids: list) -> list:
    """ D.1 選択された字幕データとAI解析結果を一括取得"""
    from app import db # 循環参照対策

    if not subtitle_ids:
        return []

    try:
        selected_subtitles = (
            db.session.query(Subtitle)
            .options(joinedload(Subtitle.analyses))
            .filter(Subtitle.subtitle_id.in_(subtitle_ids))
            .order_by(Subtitle.sequence)
            .all()
        )
        return selected_subtitles
    except SQLAlchemyError as e:
        print(f"[ERROR] get_selected_subtitlesでDBエラー: {e}")
        return []


def generate_anki_cards(analysis_data_list):
    """ D.2 選ばれた重要表現をベースに、Anki用のJSONデータを生成"""
    if not analysis_data_list:
        return []

    # Geminiに渡すインプットテキストを構築
    input_text = ""
    for idx, item in enumerate(analysis_data_list, 1):
        input_text += f"--- 表現 {idx} ---\n"
        input_text += f"覚えるべき単語/熟語: {item['target_term']}\n"
        input_text += f"元の英文: {item['raw_text']}\n"
        input_text += f"日本語訳: {item['ja_translation']}\n"
        input_text += f"解説: {item['ai_summary']}\n\n"

    prompt = f"""
        あなたはプロの英語講師であり、Anki用のフラッシュカード作成のスペシャリストです。
        提供された「ターゲット表現と文脈」を分析し、単語帳としての情報量が豊富で、かつ scannable（一目で要点がわかる）なカードデータを**指定のJSON配列**で生成してください。

        【カード作成のルール】
        1. expression (問題文):
            - ターゲットの単語・熟語部分を「 __________ (アンダーバー10個) 」にした、文脈穴埋め用の英文を作成してください。
            - 不要なHTMLタグや日本語の翻訳文などは絶対に混ぜず、純粋な英文のみにしてください。
        2. answer (正解):
            - 空欄（__________）に入る正しい単語・熟語のみを記述してください。
        3. pronunciation (発音記号):
            - 国際音声記号（IPA）を使用し、[ ] で囲んで表記してください。
        4. meaning (日本語訳):
            - 文全体の適切な日本語訳（ヒントとなる翻訳）を記述してください。
        5. synonyms (類義語・同義語):
            - カンマ区切りで、2〜3個の類義語を挙げてください。
        6. note (教師からの解説):
            - 語源、ニュアンス、フォーマル度の違い、よくある間違いなど、学習を深める豆知識を2〜3行で記述してください。
        7. 件数:
            - 入力された重要表現の数と同じだけの数を、以下の【出力フォーマット】の構造に従って配列（List）で出力してください。

        【出力フォーマット】
        余計なMarkdownの囲み（```json）や説明文は絶対に排除し、純粋なJSON配列のみを返却してください。各キーにはHTMLタグ（<br>など）を絶対に含めないでください。
        [
        {{
            "expression": "[ターゲット単語を__________に置き換えた、入力データに基づく英文]",
            "answer": "[正しい単語・熟語]",
            "pronunciation": "[正しい発音記号]",
            "meaning": "[英文全体の日本語訳]",
            "synonyms": "[類義語1, 類義語2]",
            "note": "[語源やニュアンスに関する講師からの解説]"
        }}
        ]

    【入力データ】
    {input_text}
    """

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        
        # JSONとして確実に受け取るための設定
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "max_output_tokens": 8192,  # 途中でブツ切れにならない
                "temperature": 0.3
                }
        )
        
        # 文字列として戻ってきたJSONをPythonのList[dict]に変換 Jinjaループを楽にする
        cards_data = json.loads(response.text)
        return cards_data

    except Exception as e:
        print(f"[ERROR] generate_anki_cardsでエラーが発生しました: {str(e)}")
        return None


def save_generated_cards(analysis_data_for_ai: list, generated_cards: list) -> bool:
    """ D.3 生成されたAnkiカードデータをAICardテーブルに保存"""
    from app import db # 循環参照対策

    if not generated_cards or len(analysis_data_for_ai) != len(generated_cards):
        print(f"[ERROR] データ件数が一致しません。入力: {len(analysis_data_for_ai)}件, AI出力: {len(generated_cards)}件")
        return False

    try:
        for input_item, card_item in zip(analysis_data_for_ai, generated_cards, strict=True):
            subtitle_id = input_item['subtitle_id']

            existing_card = db.session.query(AICard).filter(
                AICard.subtitle_id == subtitle_id
            ).first()

            if existing_card:
                existing_card.ai_data = card_item
                flag_modified(existing_card, "ai_data")
                print(f"[UPDATE] subtitle_id {subtitle_id} の既存カードを更新しました")
            else:
                new_card = AICard(
                    subtitle_id=input_item['subtitle_id'], # どの字幕行から作られたか紐付け
                    ai_data=card_item # すべてがJSONで保存される
                )
                db.session.add(new_card)
                print(f"[INSERT] subtitle_id {subtitle_id} の新規カードを追加しました")

        db.session.commit()
        return True

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"[ERROR] save_generated_cardsでDBエラーが発生しました: {e}")
        return False
    except ValueError as e:
        print(f"[ERROR] zip処理でデータの不整合が発生しました: {e}")
        return False


# =====================================
# E Output画面出力・CSVファイル書き出し
# =====================================
def get_generated_cards_from_db(video_id=None):
    """ E.1 AICardテーブルからカードデータの一覧を取得・整形"""
    from app import db

    try:
        # 1. 基本のクエリ（AICardを起点にする）
        query = db.session.query(AICard)

        # 2. video_id が指定されている場合、Subtitleテーブルと結合（Join）して動画IDで絞り込む
        if video_id:
            query = query.join(Subtitle, AICard.subtitle_id == Subtitle.subtitle_id)\
                    .filter(Subtitle.video_id == video_id)
            print(f"=== [DEBUG] 動画ID: {video_id} のカードを絞り込み取得します ===")
        else:
            print("=== [DEBUG] video_idが指定されていないため、すべてのカードを取得します ===")

        # クエリを実行
        generated_cards = query.all()

        print(f"=== [DEBUG] AICardから取得できた対象件数: {len(generated_cards)}件 ===")

        cards = []
        for card in generated_cards:
            # 1. まず、レコード内に ai_data (JSON) がちゃんと存在するかチェック
            # 万が一空だった場合のセーフティとして空の辞書 {} をデフォルトに
            ai_data = card.ai_data if card.ai_data else {}

            # 2. JSONの中からそれぞれの要素を取り出す
            cards.append({
                "id": card.card_id,
                "subtitle_id": card.subtitle_id,
                "expression": ai_data.get("expression", "（問題文が生成されていません）"),
                "answer": ai_data.get("answer", ""),
                "pronunciation": ai_data.get("pronunciation", ""),
                "meaning": ai_data.get("meaning", "（日本語訳がありません）"),
                "synonyms": ai_data.get("synonyms", ""),
                "note": ai_data.get("note", "（解説がありません）")
            })
            
        return cards

    except Exception as e:
        print(f"[ERROR] get_generated_cards_from_db の処理中にエラーが発生しました: {e}")
        return []

def create_csv(data) -> io.BytesIO:
    """E.2 Ankiインポート用のBOM付きCSVデータを生成"""
    output = io.StringIO()
    output.write("\ufeff")  # BOM付きで文字化け防止

    writer = csv.writer(
        output, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL
    )

    try:
        if not isinstance(data, list) or not data:
            raise ValueError("Invalid or empty data format")

        for card in data:
            expression    = card.get("expression", "")
            answer        = card.get("answer", "")
            pronunciation = card.get("pronunciation", "")
            meaning       = card.get("meaning", "")
            synonyms      = card.get("synonyms", "")
            note          = card.get("note", "")

            # Front: question sentence + meaning as hint
            front = f"{expression}<br><br>{meaning}"

            # Back: answer + pronunciation + synonyms + note
            back = f"{answer}"
            if pronunciation:
                back += f"  {pronunciation}"
            if synonyms:
                back += f"<br>類義語: {synonyms}"
            if note:
                back += f"<br><br>{note}"

            writer.writerow([front, back])

    except Exception as e:
        print(f"CSV Generation Error: {e}")

    csv_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
    output.close()
    csv_bytes.seek(0)
    return csv_bytes