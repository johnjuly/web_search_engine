import traceback
from flask import Blueprint, jsonify, abort
from ..es_connector import get_es_client
from ..config import settings
from flask import Flask, render_template, abort
import base64
snapshot_bp = Blueprint("snapshot", __name__)
es = get_es_client()

@snapshot_bp.route("view/<content_hash>")
def view_snapshot(content_hash):
    """
    渲染网页快照页面
    """
    try:
        # 查询 Elasticsearch
        result = es.get(index="web_snapshots", id=content_hash)
        print("ES get result:", result,flush=True)  # 加这一行
        if not result["found"]:
            print("Not found in ES!",flush=True) 
            abort(404, description="快照未找到")

        source = result["_source"]
        raw_html = base64.b64decode(source.get("raw_html", "")).decode("utf-8")
        # 渲染快照页面（你需要有 snapshot.html 模板）
        return render_template(
            "snapshot.html",
            url=source["url"],
            snapshot_date=source["snapshot_date"],
            content_text=source.get("content_text", ""),
            raw_html=raw_html)
    except Exception as e:
        print("Exception:", e,flush=True)  
        traceback.print_exc()
        abort(500, description=f"获取快照失败: {str(e)}")