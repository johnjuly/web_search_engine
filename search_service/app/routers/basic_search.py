from flask import Blueprint, request, jsonify
from flask_login import current_user
from ..es_connector import get_es_client
from ..config import settings
from ..models.user import user_profiles_collection
from ..models.user import user_search_history_collection
from datetime import datetime
basic_search_bp = Blueprint("basic_search", __name__)
es = get_es_client()

@basic_search_bp.route("/search", methods=["POST"])
def basic_search():
 
    """
    搜索功能
    """
    try:
        # 获取请求数据
        req_data = request.get_json()
        query = req_data.get("query", "")
        page = int(req_data.get("page", 1))
        size = int(req_data.get("size", 10))
        sort = req_data.get("sort", None)

        if current_user.is_authenticated:
            user_search_history_collection.insert_one({
                "username": current_user.id,
                "query": query,
                "search_type": "basic",
                "timestamp": datetime.utcnow().isoformat()
            })
         # 获取当前用户兴趣
        interests = []
        if current_user.is_authenticated:
            profile = user_profiles_collection.find_one({"username": current_user.id})
            if profile and profile.get("interests"):
                interests = profile["interests"]

        # 构建 should 子句用于兴趣加权
        should_clauses = []
        for tag in interests:
            should_clauses.append({
                "match": {
                    "main_content": {
                        "query": tag,
                        "boost": 3
                    }
                }
            })
            should_clauses.append({
                "match": {
                    "title": {
                        "query": tag,
                        "boost": 5
                    }
                }
            })


        # 构建 Elasticsearch 查询
        search_body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "main_content"],
                                "type": "best_fields"
                            }
                        }
                    ],
                    "should": should_clauses,
                    "minimum_should_match": 0
                }
            },
            "highlight": {
                "pre_tags": ["<em class='highlight'>"],
                "post_tags": ["</em>"],
                "fields": {
                    "title": {},
                    "main_content": {}
                }
            },
            "from": (page - 1) * size,
            "size": size
        }


        # 添加排序
        if sort:
            search_body["sort"] = [
                {field: order}
                for part in sort.split(",")
                for field, order in [part.split(":")]
            ]

        # 执行搜索
        result = es.search(index=settings.WEB_CONTENT_INDEX, body=search_body)

        # 格式化结果
        return jsonify({
            "total": result["hits"]["total"]["value"],
            "items": [
                {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "title": hit["highlight"].get("title", [hit["_source"]["title"]])[0],
                    "content": hit["highlight"].get("mai_content", [hit["_source"]["main_content"]])[0],
                    "url": hit["_source"]["url"],
                    "publish_date": hit["_source"].get("crawled_at"),
                    "content_hash": hit["_source"].get("content_hash")
                }
                for hit in result["hits"]["hits"]
            ]
        })
        
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500