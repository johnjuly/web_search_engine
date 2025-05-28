# app/routers/suggest.py
from flask import Blueprint, request, jsonify
from ..es_connector import get_es_client
import logging

# 创建蓝图
suggest_bp = Blueprint("suggest", __name__)
es = get_es_client()

# 配置日志
logger = logging.getLogger(__name__)

@suggest_bp.route("/suggest", methods=["GET"])
def get_suggestions():
    """
    获取搜索联想建议
    
    Args:
        q: 用户输入的搜索词 (必需)
        field: 搜索字段 (title 或 main_content, 默认为 title)
        size: 返回结果数量 (默认为 5)
    
    Returns:
        JSON 格式的联想建议列表
    """
    # 获取查询参数
    query = request.args.get("q", "")
    field = request.args.get("field", "title")
    size = int(request.args.get("size", 5))
    
    if not query:
        return jsonify({"suggestions": []})
    
    if field not in ["title", "main_content"]:
        return jsonify({"suggestions": []})
    
    # 构建suggest查询
    body = {
        "suggest": {
            "text": query,
            "completion": {
                "field": f"{field}_suggest",
                "size": size,
                "skip_duplicates": True
            }
        }
    }
    
    try:
        # 使用completion suggester
        response = es.search(
            index="webpages_index",
            body={
                "suggest": {
                    "web-suggestions": {
                        "prefix": query,
                        "completion": {
                            "field": f"{field}_suggest",
                            "size": size,
                            "skip_duplicates": True
                        }
                    }
                }
            }
        )
        
        suggestions = []
        
        # 解析建议结果
        if "suggest" in response and "web-suggestions" in response["suggest"]:
            for option in response["suggest"]["web-suggestions"][0]["options"]:
                source = option.get("_source", {})
                suggestions.append({
                    "text": option["text"],
                    "url": source.get("url", ""),
                    "title": source.get("title", "")[:50] + "..." if len(source.get("title", "")) > 50 else source.get("title", "")
                })
        
        return jsonify({"suggestions": suggestions})
    
    except Exception as e:
        # 使用配置的logger记录错误
        logger.error(f"联想查询失败: {str(e)}")
        return jsonify({"suggestions": [], "error": str(e)}), 500