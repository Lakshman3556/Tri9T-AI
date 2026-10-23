from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./ct200.db"
    GENERATION_STORE: Literal["json", "mongo"] = "json"
    JSON_STORE_PATH: str = "./generations.json"
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "ct200"

    LLM_PROVIDER: Literal["mock", "groq", "gemini", "openrouter"] = "mock"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = "mock-model"
    LLM_TIMEOUT_S: int = 60
    LLM_MAX_REPAIR_ATTEMPTS: int = 2

    MAX_SELECTION_CHARS: int = 12000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
