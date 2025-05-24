import hashlib
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["nankai_crawler_db"]
collection = db["webpages"]  # 你的网页集合名

for doc in collection.find():
    content = doc.get("content", "")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    collection.update_one(
        {"_id": doc["_id"]},
        {"$set": {"content_hash": content_hash}}
    )
    print(f"Updated {doc['_id']} with content_hash {content_hash}")