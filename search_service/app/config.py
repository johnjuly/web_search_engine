from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    # 定义多个索引
    DOC_SEARCH_INDEX: str = os.getenv("DOC_SEARCH_INDEX", "documents_index")  # 文档搜索索引
    WEB_CONTENT_INDEX: str = os.getenv("WEB_CONTENT_INDEX", "webpages_index")  # 网页内容搜索索引
    SNAPSHOT_INDEX: str = os.getenv("SNAPSHOT_INDEX", "web_snapshots")  # 网页快照索引
    ES_USER: str = os.getenv("ES_USER", "elastic")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "oobX44qF")
    API_PORT: int = int(os.getenv("API_PORT", 8000))

settings = Settings()