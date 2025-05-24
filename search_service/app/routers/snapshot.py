from flask import Blueprint, jsonify, abort
from ..es_connector import get_es_client
from ..config import settings
from flask import Flask, render_template, abort
snapshot_bp = Blueprint("snapshot", __name__)
es = get_es_client()

@snapshot_bp.route("/api/snapshot/view/<content_hash>")
def view_snapshot(content_hash):
    """
    渲染网页快照页面
    """
    try:
        # 查询 Elasticsearch
        result = es.get(index="web_snapshots", id=content_hash)
        if not result["found"]:
            abort(404, description="快照未找到")

        source = result["_source"]
        # 渲染快照页面（你需要有 snapshot.html 模板）
        return render_template(
            "snapshot.html",
            url=source["url"],
            snapshot_date=source["captured_at"],
            content_text=source.get("html_content", ""),
            raw_html=source.get("html_content", "")
        )
    except Exception as e:
        abort(500, description=f"获取快照失败: {str(e)}")