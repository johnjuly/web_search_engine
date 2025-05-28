from flask import Blueprint, request, jsonify
from ..es_connector import get_es_client

document_search_bp = Blueprint("document_search", __name__)
es = get_es_client()

@document_search_bp.route("/search", methods=["POST"])
def search_documents():
    data = request.json
    query = data.get("query", "")
    page = int(data.get("page", 1))
    size = int(data.get("size", 10))
    body = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["filename", "file_type", "source_page"]
            }
        },
        "from": (page - 1) * size,
        "size": size
    }
    resp = es.search(index="documents_index", body=body)
    results = []
    for hit in resp["hits"]["hits"]:
        source = hit["_source"]
        results.append({
            "id": hit["_id"],
            "filename": source.get("filename", ""),
            "file_type": source.get("file_type", ""),
            "url": source.get("url", ""),
            "source_page": source.get("source_page", ""),
            "crawled_at": source.get("crawled_at", ""),
        })
    return jsonify({
        "total": resp["hits"]["total"]["value"],
        "items": results
    })