"""
Selection API (Section 8)
Endpoints for creating and retrieving immutable, version-pinned selections.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.orm import Selection, SelectionItem, NodeVersion, DocumentVersion
from app.schemas import SelectionCreate, SelectionResponse, SelectionItemOutput
from app.services.selection import SelectionService

router = APIRouter(prefix="/selections", tags=["Selections"])


@router.post("", response_model=SelectionResponse, status_code=201)
def create_selection(data: SelectionCreate, db: Session = Depends(get_db)):
    """Creates a named, version-pinned selection of document sections."""
    service = SelectionService(db)
    selection = service.create_selection(data)
    return _serialize_selection(selection, db)


@router.get("/{selection_id}", response_model=SelectionResponse)
def get_selection(selection_id: str, db: Session = Depends(get_db)):
    """Retrieves an existing selection with its pinned node versions."""
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail=f"Selection '{selection_id}' not found.")
    return _serialize_selection(selection, db)


@router.get("/{selection_id}/text")
def get_selection_text(selection_id: str, db: Session = Depends(get_db)):
    """Returns the grounded source text reconstructed from the pinned nodes for LLM prompt generation."""
    service = SelectionService(db)
    return service.reconstruct_selection_text(selection_id)


@router.get("", response_model=List[SelectionResponse])
def list_selections(db: Session = Depends(get_db)):
    """Lists all stored selections."""
    selections = db.query(Selection).order_by(Selection.created_at.desc()).all()
    return [_serialize_selection(s, db) for s in selections]


def _serialize_selection(selection: Selection, db: Session) -> SelectionResponse:
    items_output = []
    for item in selection.items:
        nv = db.query(NodeVersion).filter(NodeVersion.id == item.node_version_id).first()
        doc_ver = db.query(DocumentVersion).filter(DocumentVersion.id == nv.document_version_id).first() if nv else None
        ver_no = doc_ver.version_no if doc_ver else 1

        items_output.append(SelectionItemOutput(
            node_id=item.logical_node_id,
            node_version_id=item.node_version_id,
            version=ver_no,
            section_number=nv.section_number if nv else "",
            heading=nv.heading if nv else "",
            pinned_hash=item.pinned_hash,
            position=item.position
        ))

    return SelectionResponse(
        selection_id=selection.id,
        name=selection.name,
        document_id=selection.document_id,
        fingerprint=selection.fingerprint,
        created_at=selection.created_at,
        items=items_output
    )
