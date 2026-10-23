"""
Node Inspection and Change Endpoints (Section 7)
"""
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.orm import LogicalNode, NodeVersion, DocumentVersion, NodeReference
from app.schemas import NodeDetail, NodeChangeResponse
from app.services.diffing import compute_word_diff
from app.services.ingest import IngestionService

router = APIRouter(tags=["Nodes"])


@router.post("/ingest/local", tags=["Documents"])
def ingest_local_pdf(
    path: str = Query(..., description="Local path to PDF"),
    document_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Convenience endpoint for local execution and demo scripts."""
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    service = IngestionService(db)
    doc_ver, already_ingested = service.ingest_pdf(pdf_path, document_id=document_id)
    return {
        "document_id": doc_ver.document_id,
        "version_id": doc_ver.id,
        "version_no": doc_ver.version_no,
        "already_ingested": already_ingested,
        "parse_status": doc_ver.parse_status
    }


@router.get("/nodes/{node_id}", response_model=NodeDetail)
def get_node_by_logical_id(
    node_id: str,
    version: Optional[int] = Query(None, description="Document version number (defaults to latest)"),
    db: Session = Depends(get_db)
):
    """Retrieves a node by its stable logical ID for a given document version."""
    logical_node = db.query(LogicalNode).filter(LogicalNode.id == node_id).first()
    if not logical_node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")

    # Find target document version
    if version is not None:
        doc_ver = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == logical_node.document_id,
            DocumentVersion.version_no == version
        ).first()
        if not doc_ver:
            raise HTTPException(status_code=404, detail=f"Version {version} not found.")
    else:
        doc_ver = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == logical_node.document_id
        ).order_by(DocumentVersion.version_no.desc()).first()

    node_ver = db.query(NodeVersion).filter(
        NodeVersion.logical_node_id == node_id,
        NodeVersion.document_version_id == doc_ver.id
    ).first()

    if not node_ver:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' does not exist in version {doc_ver.version_no}.")

    # Resolve parent logical ID
    parent_logical_id = None
    if node_ver.parent_node_version_id:
        parent_nv = db.query(NodeVersion).filter(NodeVersion.id == node_ver.parent_node_version_id).first()
        if parent_nv:
            parent_logical_id = parent_nv.logical_node_id

    # Resolve children logical IDs
    children_nvs = db.query(NodeVersion).filter(NodeVersion.parent_node_version_id == node_ver.id).all()
    children_logical_ids = [c.logical_node_id for c in children_nvs]

    # Resolve cross-references
    refs = db.query(NodeReference).filter(NodeReference.from_node_version_id == node_ver.id).all()
    ref_targets = [r.target_section_number for r in refs]

    return NodeDetail(
        node_id=node_id,
        node_version_id=node_ver.id,
        section_number=node_ver.section_number,
        heading=node_ver.heading,
        level_declared=node_ver.level_declared,
        tree_depth=node_ver.tree_depth,
        doc_order=node_ver.doc_order,
        page_start=node_ver.page_start,
        page_end=node_ver.page_end,
        own_hash=node_ver.own_hash,
        flags=node_ver.flags_json,
        body_text=node_ver.body_text,
        body_norm=node_ver.body_norm,
        blocks=node_ver.blocks_json,
        subtree_hash=node_ver.subtree_hash,
        parent_node_id=parent_logical_id,
        children_node_ids=children_logical_ids,
        references=ref_targets
    )


@router.get("/node-versions/{node_version_id}")
def get_node_version_row(node_version_id: str, db: Session = Depends(get_db)):
    """Retrieves an exact immutable pinned node_version snapshot."""
    nv = db.query(NodeVersion).filter(NodeVersion.id == node_version_id).first()
    if not nv:
        raise HTTPException(status_code=404, detail=f"Node version '{node_version_id}' not found.")
    return {
        "id": nv.id,
        "logical_node_id": nv.logical_node_id,
        "document_version_id": nv.document_version_id,
        "section_number": nv.section_number,
        "heading": nv.heading,
        "body_text": nv.body_text,
        "own_hash": nv.own_hash,
        "subtree_hash": nv.subtree_hash,
        "change_status": nv.change_status
    }


@router.get("/nodes/{node_id}/changes", response_model=NodeChangeResponse)
def get_node_changes(
    node_id: str,
    from_version: int = Query(1),
    to_version: int = Query(2),
    db: Session = Depends(get_db)
):
    """Compares a specific node across two versions with lexical significance classification."""
    logical_node = db.query(LogicalNode).filter(LogicalNode.id == node_id).first()
    if not logical_node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")

    v_from = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == logical_node.document_id,
        DocumentVersion.version_no == from_version
    ).first()
    v_to = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == logical_node.document_id,
        DocumentVersion.version_no == to_version
    ).first()

    if not v_from or not v_to:
        raise HTTPException(status_code=404, detail="Version not found.")

    nv_from = db.query(NodeVersion).filter(
        NodeVersion.logical_node_id == node_id,
        NodeVersion.document_version_id == v_from.id
    ).first()
    nv_to = db.query(NodeVersion).filter(
        NodeVersion.logical_node_id == node_id,
        NodeVersion.document_version_id == v_to.id
    ).first()

    if not nv_from and not nv_to:
        raise HTTPException(status_code=404, detail="Node does not exist in either version.")

    if not nv_from:
        return NodeChangeResponse(
            logical_node_id=node_id,
            section_number=nv_to.section_number,
            heading=nv_to.heading,
            changed=True,
            status="added",
            own_changed=True,
            subtree_changed=True,
            old_hash=None,
            new_hash=nv_to.own_hash,
            significance="material",
            diff={"info": "Newly added section"}
        )

    if not nv_to:
        return NodeChangeResponse(
            logical_node_id=node_id,
            section_number=nv_from.section_number,
            heading=nv_from.heading,
            changed=True,
            status="removed",
            own_changed=True,
            subtree_changed=True,
            old_hash=nv_from.own_hash,
            new_hash=None,
            significance="material",
            diff={"info": "Section removed in target version"}
        )

    own_changed = nv_from.own_hash != nv_to.own_hash
    subtree_changed = nv_from.subtree_hash != nv_to.subtree_hash
    changed = own_changed or subtree_changed

    diff_data = compute_word_diff(nv_from.body_norm, nv_to.body_norm)

    return NodeChangeResponse(
        logical_node_id=node_id,
        section_number=nv_to.section_number,
        heading=nv_to.heading,
        changed=changed,
        status=nv_to.change_status,
        own_changed=own_changed,
        subtree_changed=subtree_changed,
        old_hash=nv_from.own_hash,
        new_hash=nv_to.own_hash,
        significance=diff_data["significance"],
        diff=diff_data
    )
