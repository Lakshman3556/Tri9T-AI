"""
Generation Store Abstract Interface (Section 3 & 4)
Allows switching between lightweight file-based JSON storage and MongoDB.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class GenerationStore(ABC):
    @abstractmethod
    def save(self, doc: Dict[str, Any]) -> str:
        """Saves a generation document. Returns the generation _id."""
        pass

    @abstractmethod
    def get(self, gen_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a generation by its _id."""
        pass

    @abstractmethod
    def find_active_by_key(
        self, selection_fingerprint: str, prompt_version: str, model: str
    ) -> Optional[Dict[str, Any]]:
        """Finds completed generation matching the idempotent deduplication key."""
        pass

    @abstractmethod
    def list_by_selection(self, selection_id: str) -> List[Dict[str, Any]]:
        """Lists all generations for a given selection, newest first."""
        pass

    @abstractmethod
    def list_all(self) -> List[Dict[str, Any]]:
        """Lists all stored generations."""
        pass
