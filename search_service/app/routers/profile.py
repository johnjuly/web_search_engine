from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from ..models.user import user_profiles_collection
from datetime import datetime

profile_bp = Blueprint("profile", __name__)

@profile_bp.route("/profile", methods=["GET"])
@login_required
def get_profile():
    profile = user_profiles_collection.find_one({"username": current_user.id})
    if not profile:
        # 自动创建空profile
        profile = {
            "username": current_user.id,
            "role": "未设置",
            "college": "未设置",
            "age": None,
            "interests": [],
            "created_at": datetime.utcnow(),
            "last_updated": datetime.utcnow()
        }
        user_profiles_collection.insert_one(profile)
    profile.pop("_id", None)
    return jsonify(profile)

@profile_bp.route("/profile", methods=["POST"])
@login_required
def update_profile():
    data = request.get_json()
    data["last_updated"] = datetime.utcnow()
    user_profiles_collection.update_one(
        {"username": current_user.id},
        {"$set": data},
        upsert=True
    )
    return jsonify({"msg": "信息已更新"})