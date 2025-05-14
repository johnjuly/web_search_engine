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
MONGO_COLLECTION = "web_snapshots"

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
def parse_html(raw_html_binary):
    """解析压缩的HTML内容并提取可搜索文本"""
    try:
        decompressed = zlib.decompress(raw_html_binary)
        html = decompressed.decode('utf-8')
        
        soup = BeautifulSoup(html, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
            
        text = soup.get_text(separator=' ', strip=True)
        return re.sub(r'\s+', ' ', text)
    
    except Exception as e:
        logger.error(f"HTML解析失败: {str(e)}")
        return ""

def generate_actions():
    mongo_client = MongoClient(MONGO_URI)
    collection = mongo_client[MONGO_DB][MONGO_COLLECTION]
    
    for doc in collection.find().batch_size(BATCH_SIZE):
        try:
            # 兼容 raw_html 和 raw_html_content 字段
            raw_html = doc.get("raw_html") or doc.get("raw_html_content")
            
            if not raw_html:
                logger.warning(f"文档 {doc['_id']} 缺少 raw_html 和 raw_html_content 字段，已跳过")
                continue
            
            # 提取其他字段
            url = doc["url"]
            snapshot_date = doc["snapshot_date"]
            content_hash = doc["content_hash"]
            
            # 处理HTML内容
            content_text = parse_html(raw_html)
            
            # 构建ES文档
            action = {
                "_index": ES_INDEX,
                "_id": f"{content_hash}_{int(snapshot_date.timestamp())}",
                "_source": {
                    "url": url,
                    "snapshot_date": snapshot_date.isoformat(),
                    "content_hash": content_hash,
                    "content_text": content_text,
                    "status_code": doc.get("status_code", 200),
                    "raw_html": base64.b64encode(raw_html).decode('utf-8'),
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

# ---------------------------- 主程序 ----------------------------
def main():
    # 创建ES客户端
    es = Elasticsearch(
        ES_HOSTS,
        basic_auth=(ES_USER, ES_PASSWORD),
        request_timeout=30
    )
    
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