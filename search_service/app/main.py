from flask import Flask, request, jsonify, render_template, abort
from elasticsearch import Elasticsearch
from .config import settings
from .es_connector import get_es_client
import os
from flask_login import LoginManager
from .routers.auth import auth_bp
from .routers.basic_search import basic_search_bp  # 导入基本搜索蓝图
from .routers.phrase_search import phrase_search_bp
from .routers.wildcard_search import wildcard_search_bp  # 导入通配查询蓝图
from .models.user import User
from.routers.snapshot import snapshot_bp  # 导入快照蓝图
from .routers.profile import profile_bp
from .routers.history import history_bp
from .routers.document_search import document_search_bp

from search_service.app.routers import suggest

app = Flask(__name__)
app.secret_key =  "16a04150057b37e56c5a3d2e6f43ab39c465448801592b6740484aeeeffb36c4"
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(username):
    return User.get(username)

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(profile_bp, url_prefix="/api")
# 注册蓝图
app.register_blueprint(history_bp, url_prefix="/api")
app.register_blueprint(basic_search_bp, url_prefix="/api/basic")  # 添加前缀 /api
app.register_blueprint(phrase_search_bp, url_prefix="/api/phrase")
app.register_blueprint(wildcard_search_bp, url_prefix="/api/wildcard")  # 添加前缀 /api
app.register_blueprint(snapshot_bp, url_prefix="/api/snapshot")  # 添加前缀 /api
app.register_blueprint(document_search_bp, url_prefix="/api/document")  # 添加前缀 /api
app.register_blueprint(suggest.suggest_bp, url_prefix="/api")

# 配置模板目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.template_folder = os.path.join(BASE_DIR, "ui")

# 初始化 Elasticsearch 客户端
es = get_es_client()

@app.route("/")
def read_root():
    """
    渲染主页
    """
    return render_template("index.html")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.API_PORT, debug=True)