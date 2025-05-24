from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from ..models.user import User, users_collection

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data["username"]
    password = data["password"]
    if users_collection.find_one({"username": username}):
        return jsonify({"error": "用户名已存在"}), 400
    password_hash = generate_password_hash(password)
    users_collection.insert_one({"username": username, "password_hash": password_hash})
    return jsonify({"msg": "注册成功"})

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data["username"]
    password = data["password"]
    user = User.get(username)
    if user and user.check_password(password):
        login_user(user)
        return jsonify({"msg": "登录成功", "username": username})
    return jsonify({"error": "用户名或密码错误"}), 401

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"msg": "已退出登录"})

@auth_bp.route("/whoami", methods=["GET"])
def whoami():
    if current_user.is_authenticated:
        return jsonify({"username": current_user.id})
    else:
        return jsonify({"username": None})