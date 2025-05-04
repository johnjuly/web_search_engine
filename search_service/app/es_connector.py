from elasticsearch import Elasticsearch
from .config import settings
import logging

logger = logging.getLogger(__name__)

def get_es_client():
    """创建带错误重试的ES客户端"""
    try:
        es = Elasticsearch(
            hosts=[settings.ES_HOST],
            basic_auth=(settings.ES_USER, settings.ES_PASSWORD),
            request_timeout=30,
            max_retries=3,
            retry_on_timeout=True
        )
        if not es.ping():
            raise ConnectionError("Elasticsearch连接失败")
        return es
    except Exception as e:
        logger.error(f"ES连接异常: {str(e)}")
        raise