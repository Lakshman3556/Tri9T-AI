"""
MongoDB Generation Store Implementation
"""
from typing import Dict, Any, List, Optional
from app.stores.base import GenerationStore
from app.config import settings


class MongoGenerationStore(GenerationStore):
    def __init__(self):
        from pymongo import MongoClient
        self.client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
        self.db = self.client[settings.MONGODB_DB]
        self.collection = self.db["generations"]

    def save(self, doc: Dict[str, Any]) -> str:
        self.collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]

    def get(self, gen_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": gen_id})

    def find_active_by_key(
        self, selection_fingerprint: str, prompt_version: str, model: str
    ) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({
            "selection_fingerprint": selection_fingerprint,
            "prompt_version": prompt_version,
            "model": model,
            "status": {"$regex": "^completed"},
            "superseded_by": None
        })

    def list_by_selection(self, selection_id: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"selection_id": selection_id}).sort("created_at", -1)
        return list(cursor)

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self.collection.find().sort("created_at", -1))


def get_generation_store() -> GenerationStore:
    """Factory creating configured GenerationStore with JSON file fallback."""
    if settings.GENERATION_STORE == "mongo":
        try:
            store = MongoGenerationStore()
            # Ping to verify mongo is alive
            store.client.admin.command("ping")
            return store
        except Exception:
            # Fall back cleanly to JSON store if MongoDB is offline
            pass
    return JsonFileGenerationStore()
