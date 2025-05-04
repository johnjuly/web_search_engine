from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .es_connector import get_es_client
from .config import settings
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="校园通知搜索服务")


from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

app = FastAPI()

# 获取项目根目录路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 配置模板目录（指向 ui）
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "ui"))

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化ES连接
es = get_es_client()

class SearchRequest(BaseModel):
    query: str
    page: Optional[int] = 1
    size: Optional[int] = 10
    sort: Optional[str] = None  # 例如 "_score:desc, publish_date:asc"

@app.post("/search")
async def search_articles(req: SearchRequest):
    try:
        # 构建ES查询
        search_body = {
            "query": {
                "multi_match": {
                    "query": req.query,
                    "fields": ["title^3", "content"],
                    "type": "best_fields"
                }
            },
            "highlight": {
                "pre_tags": ["<em class='highlight'>"],
                "post_tags": ["</em>"],
                "fields": {
                    "title": {},
                    "content": {}
                }
            },
            "from": (req.page - 1) * req.size,
            "size": req.size
        }

        # 添加排序
        if req.sort:
            search_body["sort"] = [
                {field: order} 
                for part in req.sort.split(",") 
                for field, order in [part.split(":")]
            ]

        # 执行搜索
        result = es.search(
            index=settings.ES_INDEX,
            body=search_body
        )

        # 格式化结果
        return {
            "total": result["hits"]["total"]["value"],
            "items": [
                {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "title": hit["highlight"].get("title", [hit["_source"]["title"]])[0],
                    "content": hit["highlight"].get("content", [hit["_source"]["content"]])[0],
                    "url": hit["_source"]["url"],
                    "publish_date": hit["_source"].get("publish_date")
                }
                for hit in result["hits"]["hits"]
            ]
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"搜索失败: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT)