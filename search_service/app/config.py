from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_INDEX: str = os.getenv("ES_INDEX", "university_notices")
    ES_USER: str = os.getenv("ES_USER", "elastic")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "oobX44qF")
    API_PORT: int = int(os.getenv("API_PORT", 8000))

settings = Settings()