"""
Document and Version Ingestion Endpoints (Section 7)
"""
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.orm import Document, DocumentVersion, NodeVersion
from app.schemas import DocumentResponse, VersionSummary
from app.services.ingest import IngestionService
from app.services.diffing import compute_word_diff

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", response_model=DocumentResponse, status_code=201)
async def create_document(
    file: UploadFile = File(...),
    name: str = Form("CardioTrack CT-200 Manual"),
    db: Session = Depends(get_db)
):
    """Uploads a PDF file to create a new Document and its initial Version 1."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        service = IngestionService(db)
        doc_ver, _ = service.ingest_pdf(tmp_path, document_name=name)
        return doc_ver.document
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.post("/{doc_id}/versions", response_model=VersionSummary, status_code=201)
async def reingest_version(
    doc_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Re-ingests a modified PDF manual (e.g. v2) as a new version of an existing document."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        service = IngestionService(db)
        doc_ver, already_ingested = service.ingest_pdf(tmp_path, document_id=doc_id)
        
        # Calculate change counts
        nodes = db.query(NodeVersion).filter(NodeVersion.document_version_id == doc_ver.id).all()
        added = len([n for n in nodes if n.change_status == "added"])
        modified = len([n for n in nodes if n.change_status == "modified"])
        unchanged = len([n for n in nodes if n.change_status == "unchanged"])
        warnings = len(doc_ver.parse_report.get("warnings", []))

        return VersionSummary(
            id=doc_ver.id,
            document_id=doc_ver.document_id,
            version_no=doc_ver.version_no,
            source_filename=doc_ver.source_filename,
            file_sha256=doc_ver.file_sha256,
            page_count=doc_ver.page_count,
            ingested_at=doc_ver.ingested_at,
            parse_status=doc_ver.parse_status,
            warning_count=warnings,
            added_count=added,
            modified_count=modified,
            unchanged_count=unchanged
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("", response_model=List[DocumentResponse])
def list_documents(db: Session = Depends(get_db)):
    """Lists all stored documents."""
    return db.query(Document).order_by(Document.created_at.desc()).all()


@router.get("/{doc_id}/versions", response_model=List[VersionSummary])
def list_document_versions(doc_id: str, db: Session = Depends(get_db)):
    """Lists all versions for a document with parse status and change summaries."""
    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id
    ).order_by(DocumentVersion.version_no.asc()).all()

    summaries = []
    for ver in versions:
        nodes = db.query(NodeVersion).filter(NodeVersion.document_version_id == ver.id).all()
        added = len([n for n in nodes if n.change_status == "added"])
        modified = len([n for n in nodes if n.change_status == "modified"])
        unchanged = len([n for n in nodes if n.change_status == "unchanged"])
        warnings = len(ver.parse_report.get("warnings", []))

        summaries.append(VersionSummary(
            id=ver.id,
            document_id=ver.document_id,
            version_no=ver.version_no,
            source_filename=ver.source_filename,
            file_sha256=ver.file_sha256,
            page_count=ver.page_count,
            ingested_at=ver.ingested_at,
            parse_status=ver.parse_status,
            warning_count=warnings,
            added_count=added,
            modified_count=modified,
            unchanged_count=unchanged
        ))
    return summaries


@router.get("/{doc_id}/sections")
def list_top_level_sections(
    doc_id: str,
    version: Optional[int] = Query(None, description="Document version (defaults to latest)"),
    db: Session = Depends(get_db)
):
    """Lists top-level (level-1) sections of a document."""
    doc_ver = _resolve_doc_version(db, doc_id, version)
    level_1_nodes = db.query(NodeVersion).filter(
        NodeVersion.document_version_id == doc_ver.id,
        NodeVersion.level_declared == 1
    ).order_by(NodeVersion.doc_order.asc()).all()

    return [
        {
            "node_id": n.logical_node_id,
            "section_number": n.section_number,
            "heading": n.heading,
            "version": doc_ver.version_no,
            "own_hash": n.own_hash,
            "page_start": n.page_start
        }
        for n in level_1_nodes
    ]


@router.get("/{doc_id}/tree")
def get_document_tree(
    doc_id: str,
    version: Optional[int] = Query(None),
    include_text: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Returns the full hierarchical AST tree for a document version."""
    doc_ver = _resolve_doc_version(db, doc_id, version)
    all_nodes = db.query(NodeVersion).filter(
        NodeVersion.document_version_id == doc_ver.id
    ).order_by(NodeVersion.doc_order.asc()).all()

    # Build nested tree
    tree_nodes = {}
    root_node = None

    for n in all_nodes:
        node_payload = {
            "node_id": n.logical_node_id,
            "node_version_id": n.id,
            "section_number": n.section_number,
            "heading": n.heading,
            "level_declared": n.level_declared,
            "tree_depth": n.tree_depth,
            "doc_order": n.doc_order,
            "own_hash": n.own_hash,
            "subtree_hash": n.subtree_hash,
            "flags": n.flags_json,
            "children": []
        }
        if include_text:
            node_payload["body_text"] = n.body_text
        tree_nodes[n.id] = node_payload

        if n.parent_node_version_id is None:
            root_node = node_payload

    for n in all_nodes:
        if n.parent_node_version_id and n.parent_node_version_id in tree_nodes:
            tree_nodes[n.parent_node_version_id]["children"].append(tree_nodes[n.id])

    return root_node or {}


@router.get("/{doc_id}/changes")
def get_whole_document_changes(
    doc_id: str,
    from_version: int = Query(1),
    to_version: int = Query(2),
    db: Session = Depends(get_db)
):
    """Returns whole-document diff summary between two versions."""
    v_from = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id,
        DocumentVersion.version_no == from_version
    ).first()
    v_to = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id,
        DocumentVersion.version_no == to_version
    ).first()

    if not v_from or not v_to:
        raise HTTPException(status_code=404, detail="One or both document versions not found.")

    nodes_to = db.query(NodeVersion).filter(NodeVersion.document_version_id == v_to.id).all()
    
    modified = []
    added = []
    unchanged = []

    for n in nodes_to:
        if n.section_number == "0":
            continue
        item = {
            "node_id": n.logical_node_id,
            "section_number": n.section_number,
            "heading": n.heading,
            "change_status": n.change_status,
            "change_basis": n.change_basis
        }
        if n.change_status == "modified":
            # Compute diff with previous version
            prev_nv = db.query(NodeVersion).filter(NodeVersion.id == n.prev_node_version_id).first()
            if prev_nv:
                diff_summary = compute_word_diff(prev_nv.body_norm, n.body_norm)
                item["significance"] = diff_summary["significance"]
                item["diff"] = diff_summary
            modified.append(item)
        elif n.change_status == "added":
            added.append(item)
        else:
            unchanged.append(item)

    return {
        "document_id": doc_id,
        "from_version": from_version,
        "to_version": to_version,
        "summary": {
            "modified_count": len(modified),
            "added_count": len(added),
            "unchanged_count": len(unchanged)
        },
        "modified": modified,
        "added": added,
        "unchanged": unchanged
    }


def _resolve_doc_version(db: Session, doc_id: str, version: Optional[int]) -> DocumentVersion:
    if version is not None:
        doc_ver = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_no == version
        ).first()
        if not doc_ver:
            raise HTTPException(status_code=404, detail=f"Version {version} not found for document {doc_id}.")
        return doc_ver
    
    latest = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_id
    ).order_by(DocumentVersion.version_no.desc()).first()
    if not latest:
        raise HTTPException(status_code=404, detail=f"No versions found for document {doc_id}.")
    return latest
