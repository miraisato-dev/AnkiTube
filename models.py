# models.py
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime ,ForeignKey, Text, JSON
from sqlalchemy.sql import func

# 循環参照対策
from extensions import db

# ==================================================
# テーブル名を定数（変数）として一括定義
# ==================================================
TABLE_USERS = 'users'
TABLE_VIDEOS = 'videos'
TABLE_SUBTITLES = 'subtitles'
TABLE_SUBTITLE_ANALYSES = 'subtitle_analyses'
TABLE_AI_CARDS = 'ai_cards'

#==================================================
# モデル
#==================================================

# ユーザーテーブル
class User(db.Model):
    __tablename__ = TABLE_USERS

    id = Column(Integer, primary_key=True, autoincrement=True)
    google_id = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    name = Column(String(200), nullable=True)
    avatar = Column(String(500), nullable=True)  # Google profile picture URL
    created_at = Column(DateTime, server_default=func.now())

    # リレーション
    videos = db.relationship('Video', backref='user', lazy=True)

    # Flask-Login が必要とする4つのプロパティ
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)
    

# 動画テーブル
class Video(db.Model): # app.pyのdbを継承
    # テーブル名
    __tablename__ = TABLE_VIDEOS

    # 11桁のID
    video_id = Column(String(20), primary_key=True)
    # videoのtitle
    title = Column(String(200), nullable=False)
    channel_name = Column(String(100))
    difficulty_level = db.Column(db.String(5))  # "A2", "B1" など
    summary = db.Column(db.Text)
    duration = db.Column(db.String(20), nullable=True)
    
    # ユーザーとのrelation
    user_id = Column(Integer, ForeignKey(f'{TABLE_USERS}.id', ondelete='CASCADE'), nullable=True)

    # current_timestampより書きやすいのでfunc.now()を選んだ
    created_at = Column(DateTime, 
                        server_default=func.now(), 
                        nullable=False
                        )
    

# 字幕テーブル(生)
class Subtitle(db.Model): # app.pyのdbを継承
    __tablename__ = TABLE_SUBTITLES

    subtitle_id = Column(Integer, primary_key=True, autoincrement=True)
    # videoテーブルの参照していた行が削除された場合subtitleテーブルからも削除されるように設定
    video_id = Column(String(20), ForeignKey(f'{TABLE_VIDEOS}.video_id', ondelete='CASCADE'), nullable=False)
    # sequenceはPKにせず、単なる整数カラムにする(enumerateでDBにimportするときに番号を振る)
    sequence = Column(Integer, nullable=True)

    start_time = Column(Float, nullable=False)
    raw_text = Column(String, nullable=False)
    is_selected = Column(Boolean, default=False, server_default='0', nullable=False)

    # リレーション
    video = db.relationship('Video', backref='subtitles')
    analyses = db.relationship('SubtitleAnalyses', backref='subtitle', lazy=True)

# AI重要度分析結果テーブル
class SubtitleAnalyses(db.Model):
    # テーブル名
    __tablename__ = TABLE_SUBTITLE_ANALYSES

    subtitle_analysis_id = Column(Integer, primary_key=True)
    subtitle_id = Column(
        Integer, 
        ForeignKey(f'{TABLE_SUBTITLES}.subtitle_id', ondelete='CASCADE'), 
        nullable=False,
        index=True  # 検索用
    )

    # AIが「ここを覚えるべき！」と抽出した具体的な単語や熟語
    # 例: "pick up", "significant"
    target_term = Column(String(255), nullable=True) 

    # 修復された1文に対する、AIによる自然な日本語訳
    # 例: "その可能性は極めて低いと言わざるを得ません。"
    ja_translation = Column(Text, nullable=True)

    # AIが分類した種別。UIでの色分けや切り替えに使用
    # 例: "word", "idiom", "sentence"
    category = Column(String(50), nullable=True)
    
    importance_score = Column(Float, nullable=False)
    ai_summary = Column(Text, nullable=True)
    ai_model_name = Column(String(255), nullable=False)
    prompt_version = Column(String(255), nullable=False)
    created_at = Column(DateTime,
                        server_default=func.now())
    # 再分析された場合
    updated_at = Column(
                            DateTime, 
                            server_default=func.now(), 
                            onupdate=func.now()  # 更新時に自動で時刻を塗り替える
                        )

# ai_cards (AI加工結果)
class AICard(db.Model):
    __tablename__ = TABLE_AI_CARDS

    card_id = Column(Integer, primary_key=True)

    # どの字幕（表現）から作られたカードか紐付け（CASCADEで動画削除時にも一緒に消えるのでGoodです！）
    subtitle_id = Column(
        Integer,
        ForeignKey(f'{TABLE_SUBTITLES}.subtitle_id', ondelete='CASCADE'),
        nullable=False
    )

    # AIが返してきたJSONをdictにしたもの
    ai_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # リレーション
    subtitle = db.relationship('Subtitle', backref='ai_cards')