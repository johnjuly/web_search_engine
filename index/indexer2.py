from urllib.parse import urlparse
import os

from pymongo import MongoClient

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
documents_collection = db["documents"]

def extract_filename(url):
    """从 URL 中提取文件名"""
    parsed = urlparse(url)
    return os.path.basename(parsed.path)

def generate_document_data():
    for doc in documents_collection.find():
        filename = extract_filename(doc["url"])
        yield {
            "_index": "documents_index",
            "_id": doc["url"],  # 使用 URL 作为唯一 ID
            "_source": {
                "filename": filename,
                "file_type": doc["file_type"],
                "url": doc["url"],
                "source_page": doc["source_page"],
                "crawled_at": doc["crawled_at"]
            }
        }
# 创建文档索引
document_index = "documents_index"
mapping = {
    "mappings": {
        "properties": {
            "filename": {
                "type": "text",
                "analyzer": "ik_max_word"  # 支持中文文件名分词
            },
            "file_type": {"type": "keyword"},
            "url": {"type": "keyword"},
            "source_page": {"type": "keyword"},
            "crawled_at": {"type": "date"}
        }
    }
}

if not es.indices.exists(index=document_index):
    es.indices.create(index=document_index, body=mapping)

# 执行批量导入
success, _ = bulk(es, generate_document_data())
print(f"成功导入 {success} 条文档数据")