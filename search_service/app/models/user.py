from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["nankai_crawler_db"]
users_collection = db["users"]
user_profiles_collection = db["user_profiles"] 
user_search_history_collection = db["user_search_history"]
class User(UserMixin):
    def __init__(self, username, password_hash):
        self.id = username
        self.password_hash = password_hash

    @staticmethod
    def get(username):
        user_doc = users_collection.find_one({"username": username})
        if user_doc:
            return User(user_doc["username"], user_doc["password_hash"])
        return None

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)