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
    basic_auth=("elastic", "oobX44qF")  # 替换为你的密码
)

# 定义索引Mapping（可选，Elasticsearch会自动推断类型）
index_name = "webpages_index"
mapping = {
  "mappings": {
    "properties": {
      "title": {"type": "text", "analyzer": "ik_max_word"},
      "main_content": {"type": "text", "analyzer": "ik_max_word"},
      "url": {"type": "keyword"},
      "crawled_at": {"type": "date"}
    }
  }
}
if not es.indices.exists(index=index_name):
    es.indices.create(index=index_name, body=mapping)

# 批量导入数据
def generate_data():
    for doc in collection.find():
        yield {
            "_index": index_name,
            "_id": doc["url"],  # 指定唯一ID
            "_source": {
                "title": doc.get("title"),
                "main_content": doc.get("main_content"),
                "url": doc.get("url"),
                "crawled_at": doc.get("crawled_at")
            }
        }

# 执行批量操作
success, _ = bulk(es, generate_data())
print(f"成功导入 {success} 条数据")