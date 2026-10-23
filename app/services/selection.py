"""
Selection Service (Section 8)
Manages immutable, version-pinned selections of document sections.
Constructs grounded source excerpts with ancestor paths for LLM prompting.
Enforces character limit (413 Payload Too Large) without silent truncation.
"""
import hashlib
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.orm import Selection, SelectionItem, NodeVersion, DocumentVersion, LogicalNode
from app.schemas import SelectionCreate
from app.config import settings


def compute_selection_fingerprint(items: List[Tuple[str, str]]) -> str:
    """Computes SHA-256 fingerprint from sorted (node_version_id, pinned_hash) tuples."""
    sorted_items = sorted(items, key=lambda x: x[0])
    raw = "".join(f"{nv_id}:{p_hash}" for nv_id, p_hash in sorted_items)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SelectionService:
    def __init__(self, db: Session):
        self.db = db

    def create_selection(self, data: SelectionCreate) -> Selection:
        """Creates an immutable, version-pinned selection."""
        if not data.items:
            raise HTTPException(status_code=422, detail="Selection must contain at least one item.")

        # De-duplicate requested items by (node_id, version)
        seen_keys = set()
        deduped_inputs = []
        for item in data.items:
            k = (item.node_id, item.version)
            if k not in seen_keys:
                seen_keys.add(k)
                deduped_inputs.append(item)

        resolved_items = []
        doc_id = None

        for pos, item in enumerate(deduped_inputs):
            # Resolve logical node
            logical_node = self.db.query(LogicalNode).filter(LogicalNode.id == item.node_id).first()
            if not logical_node:
                raise HTTPException(status_code=422, detail=f"Logical node '{item.node_id}' not found.")

            if doc_id is None:
                doc_id = logical_node.document_id
            elif doc_id != logical_node.document_id:
                raise HTTPException(status_code=422, detail="All selection items must belong to the same document.")

            # Resolve target version
            if item.version is not None:
                target_doc_ver = self.db.query(DocumentVersion).filter(
                    DocumentVersion.document_id == doc_id,
                    DocumentVersion.version_no == item.version
                ).first()
                if not target_doc_ver:
                    raise HTTPException(status_code=422, detail=f"Document version {item.version} does not exist.")
            else:
                # Default to latest version
                target_doc_ver = self.db.query(DocumentVersion).filter(
                    DocumentVersion.document_id == doc_id
                ).order_by(DocumentVersion.version_no.desc()).first()

            # Find specific node version
            node_ver = self.db.query(NodeVersion).filter(
                NodeVersion.logical_node_id == item.node_id,
                NodeVersion.document_version_id == target_doc_ver.id
            ).first()

            if not node_ver:
                raise HTTPException(
                    status_code=422,
                    detail=f"Node '{item.node_id}' does not exist in document version {target_doc_ver.version_no}."
                )

            resolved_items.append((node_ver, logical_node, target_doc_ver.version_no, pos))

        fingerprint = compute_selection_fingerprint([(nv.id, nv.own_hash) for nv, _, _, _ in resolved_items])

        selection = Selection(
            name=data.name,
            document_id=doc_id,
            fingerprint=fingerprint
        )
        self.db.add(selection)
        self.db.flush()

        for nv, ln, ver_no, pos in resolved_items:
            s_item = SelectionItem(
                selection_id=selection.id,
                node_version_id=nv.id,
                logical_node_id=ln.id,
                pinned_hash=nv.own_hash,
                position=pos
            )
            self.db.add(s_item)

        self.db.commit()
        self.db.refresh(selection)
        return selection

    def get_ancestor_path(self, node_ver: NodeVersion) -> str:
        """Constructs breadcrumb path: '4 Alarms and Safety Behavior > 4.2 Error Codes'."""
        path_segments = [f"{node_ver.section_number} {node_ver.heading}"]
        curr = node_ver
        while curr.parent_node_version_id:
            parent = self.db.query(NodeVersion).filter(NodeVersion.id == curr.parent_node_version_id).first()
            if not parent or parent.section_number == "0":
                break
            path_segments.append(f"{parent.section_number} {parent.heading}")
            curr = parent
        return " > ".join(reversed(path_segments))

    def reconstruct_selection_text(self, selection_id: str) -> Dict[str, Any]:
        """
        Reconstructs the grounded XML-tagged source text sent to the LLM.
        Throws HTTP 413 if text exceeds MAX_SELECTION_CHARS.
        """
        selection = self.db.query(Selection).filter(Selection.id == selection_id).first()
        if not selection:
            raise HTTPException(status_code=404, detail=f"Selection '{selection_id}' not found.")

        doc_name = selection.document.name if selection.document else "Technical Manual"

        sections_xml = []
        source_snapshot = []

        for item in selection.items:
            nv = self.db.query(NodeVersion).filter(NodeVersion.id == item.node_version_id).first()
            if not nv:
                continue

            path = self.get_ancestor_path(nv)
            doc_ver = self.db.query(DocumentVersion).filter(DocumentVersion.id == nv.document_version_id).first()
            ver_no = doc_ver.version_no if doc_ver else 1

            sec_xml = (
                f'<section number="{nv.section_number}" heading="{nv.heading}" path="{path}">\n'
                f"{nv.body_text}\n"
                f"</section>"
            )
            sections_xml.append(sec_xml)

            source_snapshot.append({
                "logical_node_id": item.logical_node_id,
                "node_version_id": nv.id,
                "version_no": ver_no,
                "section_number": nv.section_number,
                "heading": nv.heading,
                "content_hash": nv.own_hash,
                "text_norm": nv.body_norm,
                "ancestor_path": path
            })

        full_prompt_text = (
            f'<source_document name="{doc_name}">\n'
            + "\n\n".join(sections_xml) + "\n"
            + "</source_document>"
        )

        if len(full_prompt_text) > settings.MAX_SELECTION_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"Reconstructed selection text ({len(full_prompt_text)} chars) exceeds maximum allowed limit ({settings.MAX_SELECTION_CHARS} chars)."
            )

        return {
            "selection_id": selection.id,
            "fingerprint": selection.fingerprint,
            "reconstructed_text": full_prompt_text,
            "char_count": len(full_prompt_text),
            "source_snapshot": source_snapshot
        }
