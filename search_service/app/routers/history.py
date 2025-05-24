from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from ..models.user import user_search_history_collection

history_bp = Blueprint("history", __name__)

@history_bp.route("/history", methods=["GET"])
@login_required
def get_history():
    logs = list(user_search_history_collection.find(
        {"username": current_user.id}
    ).sort("timestamp", -1).limit(50))
    for log in logs:
        log["_id"] = str(log["_id"])
    return jsonify(logs)