"""
FastAPI Main Application
Mounts all REST endpoints for document ingestion, tree browsing,
versioning, selections, LLM generation, and staleness retrieval.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import engine, Base
from app.api import documents, nodes, search, selections, generations, retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database schema
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="CardioTrack CT-200 Medical Manual QA API",
    description="Deterministic PDF manual hierarchy extraction, document versioning, QA test case generation, and retrieval-time staleness tracking.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(documents.router)
app.include_router(nodes.router)
app.include_router(search.router)
app.include_router(selections.router)
app.include_router(generations.router)
app.include_router(retrieval.router)


@app.get("/health", tags=["System"])
def health_check():
    """Health check endpoint indicating service status and active providers."""
    is_mock = settings.LLM_PROVIDER == "mock" or not settings.LLM_API_KEY
    return {
        "status": "healthy",
        "llm_provider": "mock" if is_mock else settings.LLM_PROVIDER,
        "is_mock_mode": is_mock,
        "generation_store": settings.GENERATION_STORE,
        "database": "sqlite",
    }
