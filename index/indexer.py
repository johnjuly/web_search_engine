from pymongo import MongoClient
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

# 连接MongoDB
mongo_client = MongoClient("mongodb://localhost:27017")
db = mongo_client["nankai_crawler_db"]
collection = db["webpages"]

# 连接Elasticsearch
es = Elasticsearch(
    ["http://localhost:9200"],
    basic_auth=("elastic", "oobX44qF")  
)

# 修正映射定义（添加引号并简化结构）
index_name = "webpages_index"
mapping = {
    "mappings": {
        "properties": {
            "title": {"type": "text", "analyzer": "ik_max_word"},
            "main_content": {"type": "text", "analyzer": "ik_max_word"},
            "title_suggest": {"type": "completion"},  # 独立的补全字段
            "content_suggest": {"type": "completion"},  # 独立的补全字段
            "url": {"type": "keyword"},
            "crawled_at": {"type": "date"},
            "content_hash": {"type": "keyword"}
        }
    }
}

# 删除并重建索引
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)
es.indices.create(index=index_name, body=mapping)

# 批量导入数据
def generate_data():
    for doc in collection.find():
        title = doc.get("title", "")
        content = doc.get("main_content", "")
        
        # 准备建议字段的输入（限制长度避免过大）
        title_input = title.split()[:10] if title else [""]
        content_input = content.split()[:20] if content else [""]
        
        yield {
            "_index": index_name,
            "_id": doc["url"],
            "_source": {
                "title": title,
                "main_content": content,
                "title_suggest": {
                    "input": title_input,
                    "weight": len(title)
                },
                "content_suggest": {
                    "input": content_input,
                    "weight": len(content)
                },
                "url": doc.get("url"),
                "crawled_at": doc.get("crawled_at"),
                "content_hash": doc.get("content_hash", "")
            }
        }

# 执行批量操作
success, _ = bulk(es, generate_data())
print(f"成功导入 {success} 条数据")