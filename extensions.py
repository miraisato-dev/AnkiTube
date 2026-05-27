# extensions.py db = SQLAlchemy()の定義のみ
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import MetaData


# 名札（制約）の付け方ルール
naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# ★db変数を使用してSQLAlchemyを操作できる
# ルールを適用して dbインスタンスをメタデータ付きで作る
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
# appとdbを紐づける

login_manager = LoginManager()
login_manager.login_view = 'login'  # ログインしていない場合にリダイレクトするページ
login_manager.login_message = 'ログインしてください'