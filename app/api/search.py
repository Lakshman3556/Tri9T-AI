"""
Search API (Section 7)
Provides normalized text and heading search across document versions.
Guarantees queries like 'profile' match text originally stored with Unicode ligatures.
"""
from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.orm import NodeVersion, DocumentVersion
from app.schemas import SearchResultItem
from app.parser.normalize import normalize_text

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("", response_model=List[SearchResultItem])
def search_nodes(
    q: str = Query(..., min_length=2, description="Search term"),
    document_id: Optional[str] = Query(None),
    version: Optional[int] = Query(None),
    scope: Literal["heading", "body", "all"] = Query("all"),
    db: Session = Depends(get_db)
):
    """Searches node headings and normalized body text, returning matching snippets."""
    norm_query = normalize_text(q).lower()
    
    query = db.query(NodeVersion, DocumentVersion).join(
        DocumentVersion, NodeVersion.document_version_id == DocumentVersion.id
    )

    if document_id:
        query = query.filter(DocumentVersion.document_id == document_id)

    if version is not None:
        query = query.filter(DocumentVersion.version_no == version)

    results = []
    for nv, dv in query.all():
        heading_match = norm_query in nv.heading_norm.lower() if scope in ("heading", "all") else False
        body_match = norm_query in nv.body_norm.lower() if scope in ("body", "all") else False

        if heading_match or body_match:
            snippet = ""
            if body_match:
                idx = nv.body_norm.lower().find(norm_query)
                start = max(0, idx - 40)
                end = min(len(nv.body_norm), idx + len(norm_query) + 40)
                snippet = "..." + nv.body_norm[start:end] + "..."
            else:
                snippet = nv.heading

            results.append(SearchResultItem(
                node_id=nv.logical_node_id,
                node_version_id=nv.id,
                version_no=dv.version_no,
                section_number=nv.section_number,
                heading=nv.heading,
                snippet=snippet
            ))

    return results
