"""
LLM Generation Endpoints (Section 9.1)
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.selection import SelectionService
from app.services.generation import GenerationService
from app.stores.mongo_store import get_generation_store

router = APIRouter(tags=["Generations"])


@router.post("/selections/{selection_id}/generate")
async def generate_test_cases_for_selection(
    selection_id: str,
    response: Response,
    force: bool = Query(False, description="Forces regeneration, superseding any existing generation"),
    db: Session = Depends(get_db)
):
    """Generates 3 to 5 grounded QA test cases from a version-pinned selection."""
    selection_svc = SelectionService(db)
    selection_data = selection_svc.reconstruct_selection_text(selection_id)

    store = get_generation_store()
    gen_svc = GenerationService(store)

    gen_doc, reused, status_code = await gen_svc.generate_test_cases(selection_data, force=force)
    response.status_code = status_code

    return {
        "generation_id": gen_doc["_id"],
        "selection_id": gen_doc["selection_id"],
        "status": gen_doc["status"],
        "reused": reused,
        "test_cases": gen_doc["test_cases"],
        "warnings": gen_doc.get("warnings", []),
        "created_at": gen_doc.get("created_at")
    }
