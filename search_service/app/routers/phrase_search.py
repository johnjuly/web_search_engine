from flask import Blueprint, request, jsonify
from elasticsearch import Elasticsearch
from ..es_connector import get_es_client
from ..config import settings
from datetime import datetime
from ..models.user import user_search_history_collection
from flask_login import current_user
phrase_search_bp = Blueprint("phrase_search", __name__)
es = get_es_client()

@phrase_search_bp.route("/search", methods=["POST"])
def phrase_search():
    try:
        req_data = request.get_json()
        phrase = req_data.get("phrase", "")
        fields = req_data.get("fields", ["title", "main_content"])
        page = int(req_data.get("page", 1))
        size = int(req_data.get("size", 10))

        search_body = {
            "query": {
                "multi_match": {
                    "query": phrase,
                    "fields": fields,
                    "type": "phrase"
                }
            },
            "from": (page - 1) * size,
            "size": size
        }

        result = es.search(index=settings.WEB_CONTENT_INDEX, body=search_body)
        if current_user.is_authenticated:
            user_search_history_collection.insert_one({
                "username": current_user.id,
                "query": phrase,
                "search_type": "phrase",
                "timestamp": datetime.utcnow().isoformat(),
            })
        return jsonify({
            "total": result["hits"]["total"]["value"],
            "items": [
                {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "title": hit["_source"].get("title"),
                    "content": hit["_source"].get("main_content"),
                    "url": hit["_source"].get("url"),
                    "publish_date": hit["_source"].get("crawled_at"),
                    "content_hash": hit["_source"].get("content_hash")
                }
                for hit in result["hits"]["hits"]
            ]
        })
    except Exception as e:
        return jsonify({"error": f"短语查询失败: {str(e)}"}), 500