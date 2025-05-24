import hashlib
from pymongo import MongoClient
from datetime import datetime, timezone
import logging

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# MongoDB 配置
MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = "nankai_crawler_db"
SOURCE_COLLECTION = "webpages"  # 存储爬取网页的集合
SNAPSHOT_COLLECTION = "WEB_snapshots"  # 存储快照的集合

# 初始化 MongoDB 连接
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
source_collection = db[SOURCE_COLLECTION]
snapshot_collection = db[SNAPSHOT_COLLECTION]

def generate_snapshot():
    """从爬取的网页数据生成快照并存储到 MongoDB"""
    try:
        # 查询所有爬取的网页数据
        for doc in source_collection.find():
            url = doc.get("url")
            title = doc.get("title", "未知标题")
            raw_html_content = doc.get("content")
            snapshot_date = doc.get("crawled_at", datetime.now(timezone.utc))

            if not raw_html_content:
                logger.warning(f"跳过没有 HTML 内容的文档: {url}")
                continue

            # 计算快照的唯一哈希值
            content_hash = hashlib.sha256(raw_html_content.encode("utf-8")).hexdigest()

            # 检查快照是否已存在
            if snapshot_collection.find_one({"content_hash": content_hash}):
                logger.info(f"快照已存在，跳过: {url}")
                continue

            # 构建快照文档
            snapshot_doc = {
                "url": url,
                "content_hash": content_hash,
                "html_content": raw_html_content,
                "captured_at": snapshot_date
            }

            # 存储快照到 MongoDB
            snapshot_collection.insert_one(snapshot_doc)
            logger.info(f"成功存储快照: {url}")

    except Exception as e:
        logger.error(f"生成快照时发生错误: {e}")

if __name__ == "__main__":
    generate_snapshot()