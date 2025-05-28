import base64
import zlib
from datetime import datetime
from pymongo import MongoClient
from elasticsearch import Elasticsearch, helpers
from bs4 import BeautifulSoup
import logging
import re

# ---------------------------- 配置 ----------------------------
# MongoDB
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "nankai_crawler_db"
MONGO_COLLECTION = "WEB_snapshots"

# Elasticsearch
ES_HOSTS = ["http://localhost:9200"]
ES_INDEX = "web_snapshots"
ES_USER = "elastic"
ES_PASSWORD = "oobX44qF"
BATCH_SIZE = 500  # 批量处理大小

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------------------------- 核心函数 ----------------------------
def parse_html(raw_html):
    """解析HTML内容并提取可搜索文本"""
    try:
        # 直接处理字符串，无需解压
        soup = BeautifulSoup(raw_html, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
            
        text = soup.get_text(separator=' ', strip=True)
        return re.sub(r'\s+', ' ', text)
    
    except Exception as e:
        logger.error(f"HTML解析失败: {str(e)}")
        return ""

def generate_actions():
    """从 MongoDB 生成 Elasticsearch 批量导入的文档"""
    mongo_client = MongoClient(MONGO_URI)
    collection = mongo_client[MONGO_DB][MONGO_COLLECTION]
    
    for doc in collection.find().batch_size(BATCH_SIZE):
        try:
            # 兼容 raw_html 和 html_content 字段
            raw_html = doc.get("raw_html") or doc.get("html_content")
            
            if not raw_html:
                logger.warning(f"文档 {doc['_id']} 缺少 raw_html 和 html_content 字段，已跳过")
                continue
            
            # 提取其他字段
            url = doc["url"]
            snapshot_date = doc["captured_at"]
            content_hash = doc["content_hash"]
            
            # 处理HTML内容（直接传递字符串）
            content_text = parse_html(raw_html)
            
            # 构建ES文档
            action = {
                "_index": ES_INDEX,
                "_id":  content_hash,  # 直接使用datetime对象
                "_source": {
                    "url": url,
                    "snapshot_date": snapshot_date.isoformat(),  # 转换为ISO字符串
                    "content_hash": content_hash,
                    "content_text": content_text,
                    "status_code": doc.get("status_code", 200),
                    "raw_html": base64.b64encode(raw_html.encode('utf-8')).decode('utf-8'),
                    "response_headers": {
                        k.lower(): v for k, v in doc.get("response_headers", {}).items()
                    }
                }
            }
            yield action
            
        except KeyError as e:
            logger.error(f"文档 {doc.get('_id', '')} 缺少必要字段: {str(e)}")
        except Exception as e:
            logger.error(f"文档处理异常 {doc.get('_id', '')}: {str(e)}")

def create_index(es):
    """创建 Elasticsearch 索引"""
    mapping = {
        "mappings": {
            "properties": {
                "url": {"type": "keyword"},
                "content_hash": {"type": "keyword"},
                "snapshot_date": {"type": "date"},
                "content_text": {"type": "text", "analyzer": "ik_max_word"},
                "raw_html": {"type": "text", "index": False},
                "status_code": {"type": "integer"},
                "response_headers": {"type": "object", "enabled": False}
            }
        }
    }
    if not es.indices.exists(index=ES_INDEX):
        es.indices.create(index=ES_INDEX, body=mapping)
        logger.info(f"索引 {ES_INDEX} 创建成功")
    else:
        logger.info(f"索引 {ES_INDEX} 已存在")

# ---------------------------- 主程序 ----------------------------
def main():
    # 创建ES客户端
    es = Elasticsearch(
        ES_HOSTS,
        basic_auth=(ES_USER, ES_PASSWORD),
        request_timeout=30
    )
    
    # 创建索引
    create_index(es)
    
    # 执行批量导入
    try:
        success_count, error_count = helpers.bulk(
            es,
            generate_actions(),
            stats_only=True,
            chunk_size=BATCH_SIZE,
            max_retries=3
        )
        logger.info(f"导入完成！成功: {success_count}, 失败: {error_count}")
    except Exception as e:
        logger.error(f"批量导入失败: {str(e)}")
    finally:
        es.close()

if __name__ == "__main__":
    main()