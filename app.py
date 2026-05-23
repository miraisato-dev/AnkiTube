# app.py
# Flask-Migrateの紐付け：ターミナルで flask db upgrade を実行することでmodels.pyの内容が実際のDBに反映される。
import os
import re
import json
import sqlite3

from flask import Flask, render_template, url_for, request, redirect, session, send_file, jsonify
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import SQLAlchemyError

from filters import format_time
from models import Video, Subtitle, SubtitleAnalyses, AICard

from function import (get_video_id, 
                                get_video_metadata, 
                                fetch_subtitles, 
                                save_metadata_and_subtitles,
                                analyze_subtitles_with_gemini, 
                                save_importance_analysis,
                                update_status,
                                get_selected_subtitles, 
                                generate_anki_cards, 
                                save_generated_cards, 
                                get_generated_cards_from_db,
                                create_csv
                                )


from threading import Thread



# ==================================================
# インスタンス生成
# ==================================================
app = Flask(__name__)

app.jinja_env.filters['format_time'] = format_time

# ==================================================
# Flaskに対する設定
# ==================================================
# 乱数を設定
app.config['SECRET_KEY'] = os.urandom(24)
# DBファイルの設定
base_dir = os.path.dirname(__file__)
database = 'sqlite:///' + os.path.join(base_dir, 'data.sqlite')
app.config['SQLALCHEMY_DATABASE_URI'] = database
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False



# ==================================================
# DB・Migrate設計
# ==================================================
# こうすることによりapp.pyとmodels.pyの循環を避ける
from extensions import db
db.init_app(app)

import models

# migrateを紐づける: これでflask dbコマンドが使えるようになる(Migrationができる)
migrate = Migrate(app, db)

# SQLiteでForeignKeyを有効化
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# ==================================================
# ルーティング
# ==================================================
# トップページ
@app.route('/')
def home():
    return render_template('home.html')

# 履歴ページ
@app.route('/history')
def history():
    videos = Video.query.options(
        joinedload(Video.subtitles).joinedload(Subtitle.ai_cards)
    ).order_by(Video.created_at.desc()).all()
    return render_template('history.html', videos=videos)

@app.route('/api/video/delete', methods=['POST'])
def delete_video():
    try:
        data = request.get_json()
        video_id = data.get('video_id')
        if not video_id:
            return jsonify({'error': 'video_idが指定されていません'}), 400

        conn = sqlite3.connect(os.path.join(base_dir, 'data.sqlite'))
        conn.execute('DELETE FROM ai_cards WHERE subtitle_id IN (SELECT subtitle_id FROM subtitles WHERE video_id=?)', (video_id,))
        conn.execute('DELETE FROM subtitle_analyses WHERE subtitle_id IN (SELECT subtitle_id FROM subtitles WHERE video_id=?)', (video_id,))
        conn.execute('DELETE FROM subtitles WHERE video_id=?', (video_id,))
        conn.execute('DELETE FROM videos WHERE video_id=?', (video_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"動画削除中にエラー: {str(e)}")
        return jsonify({'error': '削除に失敗しました'}), 500



# ビデオごとの処理進捗を管理する辞書
processing_progress = {}

# URLを受け取って処理を開始するルート
@app.route('/get_subtitles', methods=['POST'])
def get_subtitles():
    # 1. フォームからURLを取得してIDを抜く
    url = request.form.get('youtube_url')
    # 2. function.py の職人に ID抽出を頼む
    video_id = get_video_id(url)
    if not video_id:
        return "URLが正しくありません", 400
    
    # 3. セッションに「今編集中のID」を保存
    session['current_video_id'] = video_id

    # 進捗を初期化
    processing_progress[video_id] = {'percent': 0, 'message': '準備中...', 'done': False}

    def process():
        with app.app_context():
            try:
                # ステップ1: メタデータ・字幕取得
                processing_progress[video_id] = {'percent': 5, 'message': '字幕を取得しています...', 'done': False}
                
                existing_video = Video.query.get(video_id)
                if not existing_video:
                    metadata = get_video_metadata(video_id)
                    fetched = fetch_subtitles(video_id)
                    
                    if metadata and fetched:
                        # ステップ2: DB保存
                        processing_progress[video_id] = {'percent': 15, 'message': 'データを保存しています...', 'done': False}
                        save_metadata_and_subtitles(metadata, fetched)

                else:
                    print(f"=== [DEBUG] 既にDBに存在する動画です (ID: {video_id}) ===")

                
                # ステップ2: AI分析
                analysis_exists = db.session.query(SubtitleAnalyses).join(Subtitle).filter(Subtitle.video_id == video_id).first()

                if not analysis_exists:
                    print("=== [DEBUG] AI分析データ未作成のため、Gemini解析を開始します ===")
                    processing_progress[video_id] = {'percent': 20, 'message': 'AIが分析を開始します...', 'done': False}

                    subtitles_from_db = Subtitle.query.filter_by(video_id=video_id).order_by(Subtitle.sequence).all()
                    subtitles_data_for_ai = json.dumps([
                        {"sequence": s.sequence, "text": s.raw_text} for s in subtitles_from_db
                    ], ensure_ascii=False)

                    total_chunks = max(1, (len(subtitles_from_db) + 19) // 20)

                    def on_chunk_progress(current_chunk):
                        percent = 20 + int((current_chunk / total_chunks) * 70)
                        processing_progress[video_id] = {
                            'percent': percent,
                            'message': f'AIが分析中... ({current_chunk}/{total_chunks})',
                            'done': False
                        }

                    analysis_package = analyze_subtitles_with_gemini(subtitles_data_for_ai, on_chunk_progress)

                    if analysis_package:
                        processing_progress[video_id] = {'percent': 92, 'message': '分析結果を保存しています...', 'done': False}
                        video = Video.query.get(video_id)
                        if video:
                            video.difficulty_level = analysis_package.get("difficulty_level")
                            db.session.commit()
                        save_importance_analysis(subtitles_from_db, analysis_package)
                    else:
                        print("=== [ERROR] Geminiからの応答が空、またはパースに失敗しました ===")
                else:
                    print("=== [DEBUG] AI分析データは既に存在するため解析をスキップします ===")

                # 完了
                processing_progress[video_id] = {'percent': 100, 'message': '完了！', 'done': True}

            except Exception as e:
                print(f"[ERROR in background thread]: {e}")
                processing_progress[video_id] = {'percent': 0, 'message': 'エラーが発生しました', 'done': True, 'error': True}

    Thread(target=process).start()
    return redirect(url_for('loading', video_id=video_id))




    # # DBから既存の動画をチェック
    # existing_video = Video.query.get(video_id)

    # if not existing_video:
    #     print(f"=== [DEBUG] 新規動画です。データを取得します (ID: {video_id}) ===")
    #     # A. メタデータ取得
    #     metadata = get_video_metadata(video_id)
    #     # B. 字幕取得
    #     fetched = fetch_subtitles(video_id)
        
    #     if metadata and fetched:
    #         # C. 動画と字幕をDBに保存
    #         save_metadata_and_subtitles(metadata, fetched)
    # else:
    #     print(f"=== [DEBUG] 既にDBに存在する動画です (ID: {video_id}) ===")

    # # 【重要】既存動画であっても、AI分析データ(SubtitleAnalysis)が空っぽなら解析を実行する
    # analysis_exists = db.session.query(SubtitleAnalyses).join(Subtitle).filter(Subtitle.video_id == video_id).first()

    # if not analysis_exists:
    #     print("=== [DEBUG] AI分析データ未作成のため、Gemini解析を開始します ===")
        
    #     # 字幕データをDBから取得してAI用のJSONを作る
    #     subtitles_from_db = Subtitle.query.filter_by(video_id=video_id).order_by(Subtitle.sequence).all()
    #     subtitles_data_for_ai = json.dumps([
    #         {"sequence": s.sequence, "text": s.raw_text} for s in subtitles_from_db
    #     ], ensure_ascii=False)

    #     # 2.5-flash で解析
    #     analysis_package = analyze_subtitles_with_gemini(subtitles_data_for_ai)
        
    #     if analysis_package:
    #         # 難易度(difficulty_level)をVideoテーブルに保存
    #         video = Video.query.get(video_id)
    #         if video:
    #             video.difficulty_level = analysis_package.get("difficulty_level")
    #             db.session.commit()
            
    #         # 最新の save_importance_analysis(video_id, analysis_results) の形に合わせて呼び出す
    #         save_importance_analysis(subtitles_from_db, analysis_package)
    #     else:
    #         print("=== [ERROR] Geminiからの応答が空、またはパースに失敗しました ===")
    # else:
    #     print("=== [DEBUG] AI分析データは既に存在するため解析をスキップします ===")

    # # 4. 全て終わったらEditor画面へリダイレクト
    # return redirect(url_for('editor', video_id=video_id))


@app.route('/loading/<video_id>')
def loading(video_id):
    return render_template('loading.html', video_id=video_id)

@app.route('/api/status/<video_id>')
def check_status(video_id):
    progress = processing_progress.get(video_id, {
        'percent': 0, 'message': '準備中...', 'done': False
    })
    return jsonify(progress)


# 編集ページ
@app.route('/editor/<video_id>')
def editor(video_id):
    # 動画そのものの情報を取得
    video = Video.query.get(video_id)
    # 字幕データと、もしあればAIの分析結果を一緒に取得
    # 字幕(Subtitle)を主軸に、その分析結果(analyses)を結合して取得する例
    subtitles = Subtitle.query.filter_by(video_id=video_id).order_by(Subtitle.sequence).all()

    # 直接URLを叩いて入った時のために、ここでもセッションを更新しておく
    session['current_video_id'] = video_id
    
    # テンプレートに渡す
    return render_template('editor.html', video=video, subtitles=subtitles, video_id=video_id)


# ====================================================
# ユーザー選択: 字幕の選択状態を更新するAPIエンドポイント
# ====================================================
@app.route('/api/subtitle/update_status', methods=['POST'])
def handle_update_status():
    data = request.get_json()
    
    # フロントから送られてくるパラメータの取得
    subtitle_id = data.get('subtitle_id')
    status = data.get('status')
    
    # バリデーション（簡易）
    if subtitle_id is None or status not in [0, 1]:
        return jsonify({'result': 'Error', 'message': '不正なパラメータです'}), 400
        
    try:
        # 設計通りの関数を呼び出し
        result = update_status(int(subtitle_id), int(status))
        return jsonify({'result': result}), 200
        
    except ValueError as ve:
        # 該当IDなしのエラーハンドリング
        return jsonify({'result': 'Error', 'message': str(ve)}), 404
        
    except SQLAlchemyError:
        # DBエラーのエラーハンドリング
        return jsonify({'result': 'Error', 'message': 'データベースエラーが発生しました'}), 500

@app.route('/api/anki/generate', methods=['POST'])
def generate_anki_cards_api():
    try:
        data = request.get_json()
        subtitle_ids = data.get('subtitle_ids', [])
        
        if not subtitle_ids:
            return jsonify({'error': '字幕が選択されていません'}), 400

        # 【設計書関数 ①】 選択された字幕データとAI解析結果を一括取得
        selected_subtitles = get_selected_subtitles(subtitle_ids)
        if not selected_subtitles:
            return jsonify({'error': '対象の字幕データが見つかりません'}), 404

        # ② Geminiに渡すための情報（文脈）をパッケージングする（データ加工）
        analysis_data_for_ai = []
        for sub in selected_subtitles:
            word_data = next((a for a in sub.analyses if a.category in ['word', 'idiom']), None)
            sentence_data = next((a for a in sub.analyses if a.category == 'sentence'), None)

            if word_data and word_data.target_term:
                analysis_data_for_ai.append({
                    'subtitle_id': sub.subtitle_id,
                    'raw_text': sub.raw_text, # ◀️ restored_sentence は排除して一本化済み！
                    'ja_translation': sentence_data.ja_translation if sentence_data else '',
                    'target_term': word_data.target_term,
                    'ai_summary': word_data.ai_summary or ''
                })

        if not analysis_data_for_ai:
            return jsonify({
                'error': '選択された行に「覚える表現」が含まれていません。AI推薦のバッジがついている行をチェックしてください。'
            }), 400
        
        # 【設計書関数 ②】 Geminiを呼び出してAnki用のカードを生成！
        generated_cards = generate_anki_cards(analysis_data_for_ai)
        if not generated_cards or not isinstance(generated_cards, list):
            return jsonify({'error': 'Geminiによるカード生成に失敗しました（レスポンス不正）'}), 500

        # セッションに保存
        session['generated_cards'] = generated_cards

        # 【設計書関数 ③】 生成されたカードを `ai_cards` テーブルへ保存
        is_success = save_generated_cards(analysis_data_for_ai, generated_cards)
        if not is_success:
            return jsonify({'error': 'データベースへのカード保存に失敗しました'}), 500

        # フロントエンド（ブラウザ）へ成功メッセージとカードデータを返す
        return jsonify({
            'message': 'Ankiカードの生成およびDB保存に成功しました！',
            'cards': generated_cards
        }), 200

    except Exception as e:
        print(f"Anki生成エンドポイントで予期せぬエラー: {str(e)}")
        return jsonify({'error': 'サーバー内部でエラーが発生しました'}), 500


@app.route('/output')
def output():
    try:
        # セッションから「今処理している動画ID」を取り出す
        current_video_id = session.get('current_video_id')
        
        # 1. データベースから生成されたカードを直接すべて取得
        cards = get_generated_cards_from_db(video_id=current_video_id)
        
        # これでターミナル（黒い画面）に何件取得できたか表示されます
        print(f"==================================================")
        print(f"★ [CRITICAL DEBUG] /output画面で読み込んだカード数: {len(cards)}件")
        print(f"==================================================")

        video_title = 'ankitube_cards'
        if current_video_id:
            video = db.session.get(Video, current_video_id)
            if video and video.title:
                video_title = re.sub(r'\s+', '_', video.title)

        # データベースが本当に空だった場合だけのセーフティ
        if not cards:
            print("[WARNING] AICardテーブルが空です。セーフティデータを表示します。")
            cards = [
                {
                    "id": 0,
                    "subtitle_id": 0,
                    "expression": "This is a [conspicuously] placed example question.",
                    "answer": "conspicuously",
                    "pronunciation": "/kənˈspɪk.ju.əs.li/",
                    "meaning": "目立って、際立って",
                    "synonyms": "noticeably, outstandingly",
                    "note": "In a way that is clearly visible or attracts attention."
                }
            ]

    except Exception as e:
        print(f"[ERROR in /output route]: {e}")
        cards = []

    # 3. HTMLマクロ側にそのまま引き渡し
    return render_template('output.html', cards=cards, video_title=video_title)

@app.route('/output/<video_id>')
def output_by_id(video_id):
    # use video_id from URL instead of session
    cards = get_generated_cards_from_db(video_id=video_id)
    
    video_title = 'ankitube_cards'
    video = db.session.get(Video, video_id)
    if video and video.title:
        video_title = re.sub(r'\s+', '_', video.title)

    if not cards:
        cards = []

    return render_template('output.html', cards=cards, video_title=video_title)


@app.route('/api/anki/update_card', methods=['POST'])
def handle_update_card():
    """フロントから個別に届いたカードの編集内容（表現、意味、正解など）を処理する窓口"""
    data = request.get_json()
    
    subtitle_id = data.get('subtitle_id')
    
    # JavaScriptから個別に送られてくる生テキストを取得
    exp_val  = data.get('expression')
    ans_val  = data.get('answer')
    pron_val = data.get('pronunciation', '')
    mean_val = data.get('meaning')
    syn_val  = data.get('synonyms', '')
    note_val = data.get('note', '')
    
    # 必須パラメータ（最低限必要なもの）が揃っているかチェック
    if not subtitle_id or exp_val is None or ans_val is None or mean_val is None:
        return jsonify({'result': 'Error', 'message': '不正なパラメータです。必須データが不足しています。'}), 400
        
    try:
        # 1. データベースから該当するカードを検索
        card = db.session.query(AICard).filter(AICard.subtitle_id == int(subtitle_id)).first()
        
        if not card:
            return jsonify({'result': 'Error', 'message': f'subtitle_id {subtitle_id} に紐づくカードが見つかりません。'}), 404
            
        # モデルに個別のカラム（expression等）が直接存在する場合の安全な代入
        if hasattr(card, 'expression'): card.expression = exp_val
        if hasattr(card, 'answer'): card.answer = ans_val
        if hasattr(card, 'pronunciation'): card.pronunciation = pron_val
        if hasattr(card, 'meaning'): card.meaning = mean_val
        if hasattr(card, 'synonyms'): card.synonyms = syn_val
        if hasattr(card, 'note'): card.note = note_val
        
        # 4. バックアップ用JSONデータ（ai_data）の同期
        if card.ai_data and isinstance(card.ai_data, dict):
            updated_ai_data = dict(card.ai_data)
            
            # JSONの内部テキストを一括更新
            updated_ai_data['expression'] = exp_val
            updated_ai_data['answer'] = ans_val
            updated_ai_data['pronunciation'] = pron_val
            updated_ai_data['meaning'] = mean_val
            updated_ai_data['synonyms'] = syn_val
            updated_ai_data['note'] = note_val
            
            card.ai_data = updated_ai_data
            # SQLAlchemyに「JSONが書き換わったよ」と明示的に通知して保存を確定させる
            flag_modified(card, "ai_data")
            
        # 5. データベースをコミット
        db.session.commit()
        
        print(f"=== [SUCCESS] カード(ID: {subtitle_id})の個別データを元に、DB更新＆HTML自動組み立てに成功！ ===")
        return jsonify({
            'result': 'Success', 
            'message': 'カードをデータベースに一括保存しました'
        }), 200
        
    except Exception as e:
        db.session.rollback()  # エラー時は安全のために巻き戻す
        print(f"[ERROR] データベースの一括更新に失敗: {str(e)}")
        return jsonify({'result': 'Error', 'message': f'データベースの更新に失敗しました: {str(e)}'}), 500


@app.route('/api/anki/delete_card', methods=['POST'])
def delete_anki_card():
    try:
        data = request.get_json()
        subtitle_id = data.get('subtitle_id')

        if not subtitle_id:
            return jsonify({'error': 'subtitle_idが指定されていません'}), 400

        card = AICard.query.filter_by(subtitle_id=subtitle_id).first()
        if not card:
            return jsonify({'error': 'カードが見つかりません'}), 404

        db.session.delete(card)

        subtitle = Subtitle.query.filter_by(subtitle_id=subtitle_id).first()
        if subtitle:
            subtitle.is_selected = False

        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        print(f"カード削除中にエラー: {str(e)}")
        return jsonify({'error': '削除に失敗しました'}), 500


def sanitize_filename(title: str, max_length: int = 50) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', '', title)
    sanitized = sanitized.replace(' ', '_')
    return sanitized[:max_length] or 'ankitube_cards'

@app.route('/api/anki/download_csv', methods=['POST'])
def download_anki_csv():
    """
    ダウンロードボタンが押されたら、DBから最新データを引っ張ってきて
    その場でCSV（TSV）に変換し、ブラウザへ直接送り出す
    """
    try:
        data = request.get_json()
        subtitle_ids = data.get('subtitle_ids', []) # 画面で選択（チェック）されている字幕IDのリスト
        
        if not subtitle_ids:
            return jsonify({'error': '対象のカードが選択されていません'}), 400

        #【ここがポイント！】画面で編集され、リアルタイムに保存された「最新の状態」をDBからガッと取得（SELECT）
        cards_from_db = (
            db.session.query(AICard)
            .filter(AICard.subtitle_id.in_(subtitle_ids))
            .all()
        )

        if not cards_from_db:
            return jsonify({'error': '保存されたカードデータが見つかりません'}), 404

        # 引数の data 形式（辞書のリスト）に合わせてデータを整える
        csv_data = []
        for card in cards_from_db:
            ai = card.ai_data if card.ai_data else {}
            csv_data.append({
                'expression':    ai.get('expression', ''),
                'answer':        ai.get('answer', ''),
                'pronunciation': ai.get('pronunciation', ''),
                'meaning':       ai.get('meaning', ''),
                'synonyms':      ai.get('synonyms', ''),
                'note':          ai.get('note', '')
            })

        csv_file = create_csv(csv_data)
        
        # 1. セッションから現在の動画IDを取得
        # current_video_id = session.get('current_video_id')
        # print(f"[DEBUG 1] セッションから取れた動画ID: {current_video_id}")

        # video_title = ''
        
        # if current_video_id:
        #     # 2. DBから対象の動画情報を検索
        #     video = db.session.get(Video, current_video_id)
        #     print(f"[DEBUG 2] DBから動画が取得できたか: {video is not None}")
        #     if video:
        #         print(f"[DEBUG 3] DBに保存されている動画タイトル: {video.title}")
        #         video_title = video.title

        # # 3. フロントから送られてきたfilenameがなければ、動画タイトル（それもなければデフォルト値）を使う
        # filename_input = data.get('filename')
        # print(f"[DEBUG 4] フロント(JS)から届いたfilename: '{filename_input}'")

        # if not filename_input:  # None または '' の場合
        #     filename_input = video_title
        #     print(f"[DEBUG 5] フロントが空だったので動画タイトルを採用: '{filename_input}'")

        # filename = sanitize_filename(filename_input) if filename_input else 'ankitube_cards'
        # print(f"[DEBUG 6] サニタイズ後の最終ファイル名: '{filename}'")

        # === 【ここからファイル名決定ロジック】 ===
        # フロント（JS）から届いたファイル名を取得
        filename_input = data.get('filename', '').strip()

        # もしフロントから届いた名前が空、あるいはデフォルト値のままだった場合の保険として
        # セッションから動画タイトルを取得して補完する
        if not filename_input or filename_input == 'ankitube_cards':
            current_video_id = session.get('current_video_id')
            if current_video_id:
                video = db.session.get(Video, current_video_id)
                if video and video.title:
                    filename_input = video.title

        # ファイル名のサニタイズ（禁止文字の除去）。それでも空なら最終フォールバック
        filename = sanitize_filename(filename_input) if filename_input else 'ankitube_cards'
        # === 【ここまで】 ===

        # ブラウザに対して「これをファイルとして手元に保存してね！」と直接ダウンロードさせる
        return send_file(
            csv_file,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{filename}.csv'
        )

    except Exception as e:
        print(f"CSVダウンロード中にエラーが発生しました: {str(e)}")
        return jsonify({'error': 'CSVの生成・ダウンロードに失敗しました'}), 500
    

# =====================
# 実行
# =====================
if __name__ == "__main__":
    app.run(debug=False)
