"""
Retrieval API (Section 11)
Endpoints for querying generated test cases with visible, dynamic staleness metadata.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.orm import Selection, LogicalNode, DocumentVersion, NodeVersion
from app.stores.mongo_store import get_generation_store
from app.services.staleness import StalenessEvaluator

router = APIRouter(tags=["Retrieval & Staleness"])


@router.get("/selections/{selection_id}/test-cases")
def get_selection_test_cases(
    selection_id: str,
    against_version: Optional[int] = Query(None, description="Version to compare against (defaults to latest)"),
    db: Session = Depends(get_db)
):
    """Retrieves all generations for a selection with per-test-case staleness indicators."""
    store = get_generation_store()
    generations = store.list_by_selection(selection_id)
    if not generations:
        raise HTTPException(status_code=404, detail=f"No test cases generated for selection '{selection_id}'.")

    evaluator = StalenessEvaluator(db)
    return [evaluator.evaluate_generation(g, against_version=against_version) for g in generations]


@router.get("/generations/{generation_id}")
def get_generation_detail(
    generation_id: str,
    against_version: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Retrieves a single generation document with dynamic staleness evaluation."""
    store = get_generation_store()
    gen = store.get(generation_id)
    if not gen:
        raise HTTPException(status_code=404, detail=f"Generation '{generation_id}' not found.")

    evaluator = StalenessEvaluator(db)
    return evaluator.evaluate_generation(gen, against_version=against_version)


@router.get("/nodes/{node_id}/test-cases")
def get_test_cases_by_node(
    node_id: str,
    against_version: Optional[int] = Query(None),
    only_stale: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Retrieves every test case referencing this logical node across all historical generations."""
    logical_node = db.query(LogicalNode).filter(LogicalNode.id == node_id).first()
    if not logical_node:
        raise HTTPException(status_code=404, detail=f"Logical node '{node_id}' not found.")

    store = get_generation_store()
    all_gens = store.list_all()

    evaluator = StalenessEvaluator(db)
    matched_cases = []

    for gen in all_gens:
        # Check if logical_node_id is in source snapshot
        snapshot_node_ids = {s["logical_node_id"] for s in gen.get("source_snapshot", [])}
        if node_id in snapshot_node_ids:
            evaluated = evaluator.evaluate_generation(gen, against_version=against_version)
            for tc in evaluated.get("test_cases", []):
                if only_stale and tc.get("staleness", {}).get("status") not in ("likely_stale", "review_recommended"):
                    continue
                matched_cases.append({
                    "generation_id": gen["_id"],
                    "test_case": tc
                })

    return matched_cases


@router.get("/documents/{doc_id}/impact")
def get_document_version_impact(
    doc_id: str,
    from_version: int = Query(1),
    to_version: int = Query(2),
    db: Session = Depends(get_db)
):
    """Returns all test cases affected by the transition from from_version to to_version."""
    store = get_generation_store()
    all_gens = store.list_all()
    evaluator = StalenessEvaluator(db)

    impact_groups = {
        "likely_stale": [],
        "review_recommended": [],
        "probably_valid": [],
        "fresh": []
    }

    for gen in all_gens:
        evaluated = evaluator.evaluate_generation(gen, against_version=to_version)
        for tc in evaluated.get("test_cases", []):
            st = tc.get("staleness", {}).get("status", "fresh")
            impact_groups.setdefault(st, []).append({
                "generation_id": gen["_id"],
                "test_case_id": tc.get("id"),
                "title": tc.get("title"),
                "source_sections": tc.get("source_sections"),
                "reasons": tc.get("staleness", {}).get("reasons", [])
            })

    return {
        "document_id": doc_id,
        "from_version": from_version,
        "to_version": to_version,
        "impact_summary": {k: len(v) for k, v in impact_groups.items()},
        "affected_test_cases": impact_groups
    }
