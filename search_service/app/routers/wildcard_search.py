from flask import Blueprint, request, jsonify
from elasticsearch import Elasticsearch
from ..es_connector import get_es_client
from ..config import settings
from flask_login import current_user
from datetime import datetime
from ..models.user import user_search_history_collection
# 创建蓝图
wildcard_search_bp = Blueprint("wildcard_search", __name__)

# 初始化 Elasticsearch 客户端
es = get_es_client()

@wildcard_search_bp.route("/search", methods=["POST"])
def wildcard_search():
    """
    通配符查询功能
    """
    try:
        # 获取请求数据
        req_data = request.get_json()
        field = req_data.get("field", "main_content")  # 查询字段，默认是 "content"
        query = req_data.get("query", "")  # 查询内容
        page = int(req_data.get("page", 1))  # 页码
        size = int(req_data.get("size", 10))  # 每页大小
        use_regex = req_data.get("use_regex", False)  # 是否使用正则查询
        prefix = req_data.get("prefix", False)  # 是否使用前缀查询
        suffix = req_data.get("suffix", False)  # 是否使用后缀查询
        fuzzy = req_data.get("fuzzy", False)  # 是否使用模糊查询

        # 构建 Elasticsearch 查询
        if use_regex:
            # 使用正则表达式查询
            search_body = {
                "query": {
                    "regexp": {
                        field: {
                            "value": query.replace("_", ".*").replace("？", "."),
                            "case_insensitive": True  # 忽略大小写
                        }
                    }
                },
                "from": (page - 1) * size,  # 分页起始位置
                "size": size  # 每页大小
            }
        elif prefix:
            # 使用前缀查询
            search_body = {
                "query": {
                    "prefix": {
                        field: {
                            "value": query,
                            "case_insensitive": True  # 忽略大小写
                        }
                    }
                },
                "from": (page - 1) * size,
                "size": size
            }
        elif suffix:
            # 使用后缀查询（通过正则实现）
            search_body = {
                "query": {
                    "regexp": {
                        field: {
                            "value": f".*{query}",
                            "case_insensitive": True  # 忽略大小写
                        }
                    }
                },
                "from": (page - 1) * size,
                "size": size
            }
        elif fuzzy:
            # 使用模糊查询
            search_body = {
                "query": {
                    "fuzzy": {
                        field: {
                            "value": query,
                            "fuzziness": "AUTO"  # 自动模糊级别
                        }
                    }
                },
                "from": (page - 1) * size,
                "size": size
            }
        else:
            # 使用通配符查询
            search_body = {
                "query": {
                    "wildcard": {
                        field: {
                            "value": query.replace("_", "*").replace("？", "?"),
                            "case_insensitive": True  # 忽略大小写
                        }
                    }
                },
                "from": (page - 1) * size,  # 分页起始位置
                "size": size  # 每页大小
            }

        # 执行查询
        result = es.search( index=settings.WEB_CONTENT_INDEX, body=search_body)
        if current_user.is_authenticated:
            user_search_history_collection.insert_one({
                "username": current_user.id,
                "query": query,
                "search_type": "wildcard",
                "timestamp": datetime.utcnow().isoformat()
            })
        # 格式化结果
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
        return jsonify({"error": f"通配查询失败: {str(e)}"}), 500