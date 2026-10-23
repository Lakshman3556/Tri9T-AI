"""
JSON File-Backed Generation Store (Default Zero-Setup Backend)
Persists generations directly to a local JSON file (generations.json).
Thread-safe using threading.Lock.
"""
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.stores.base import GenerationStore
from app.config import settings


class JsonFileGenerationStore(GenerationStore):
    def __init__(self, file_path: Optional[str] = None):
        self.path = Path(file_path or settings.JSON_STORE_PATH)
        self.lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        with self.lock:
            if not self.path.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump([], f)

    def _read_all(self) -> List[Dict[str, Any]]:
        with self.lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []

    def _write_all(self, docs: List[Dict[str, Any]]):
        with self.lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(docs, f, indent=2, ensure_ascii=False)

    def save(self, doc: Dict[str, Any]) -> str:
        docs = self._read_all()
        # If exists, update; else append
        existing_idx = next((i for i, d in enumerate(docs) if d.get("_id") == doc["_id"]), -1)
        if existing_idx >= 0:
            docs[existing_idx] = doc
        else:
            docs.append(doc)
        self._write_all(docs)
        return doc["_id"]

    def get(self, gen_id: str) -> Optional[Dict[str, Any]]:
        docs = self._read_all()
        return next((d for d in docs if d.get("_id") == gen_id), None)

    def find_active_by_key(
        self, selection_fingerprint: str, prompt_version: str, model: str
    ) -> Optional[Dict[str, Any]]:
        docs = self._read_all()
        for d in reversed(docs):
            if (
                d.get("selection_fingerprint") == selection_fingerprint
                and d.get("prompt_version") == prompt_version
                and d.get("model") == model
                and str(d.get("status", "")).startswith("completed")
                and d.get("superseded_by") is None
            ):
                return d
        return None

    def list_by_selection(self, selection_id: str) -> List[Dict[str, Any]]:
        docs = self._read_all()
        matching = [d for d in docs if d.get("selection_id") == selection_id]
        return sorted(matching, key=lambda d: d.get("created_at", ""), reverse=True)

    def list_all(self) -> List[Dict[str, Any]]:
        return self._read_all()
