"""
Document Ingestion Service (Section 6.1)
Coordinates:
- PDF SHA-256 fingerprinting and idempotency checks
- Calling parser to extract AST, invariants, and parse report
- Running multi-pass matcher against previous version
- Preserving logical_node identity for unchanged/modified nodes
- Persisting immutable node_versions and references in an atomic transaction
"""
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.orm import Document, DocumentVersion, LogicalNode, NodeVersion, NodeReference
from app.parser.extract import parse_pdf_document
from app.services.matching import VersionMatcher
from app.parser.tree import DocumentNode


def compute_file_sha256(filepath: Path) -> str:
    """Computes SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class IngestionService:
    def __init__(self, db: Session):
        self.db = db

    def ingest_pdf(
        self,
        pdf_path: Path,
        document_id: str = None,
        document_name: str = None
    ) -> Tuple[DocumentVersion, bool]:
        """
        Ingests a PDF file.
        If document_id is None, creates a new Document with version_no=1.
        Otherwise, appends version_no = max(version) + 1.
        Returns (DocumentVersion, already_ingested: bool).
        """
        file_sha = compute_file_sha256(pdf_path)

        # 1. Resolve Document
        if not document_id:
            doc = Document(name=document_name or "CardioTrack CT-200 Manual")
            self.db.add(doc)
            self.db.flush()
            document_id = doc.id
            version_no = 1
            prev_doc_version = None
        else:
            doc = self.db.query(Document).filter(Document.id == document_id).first()
            if not doc:
                raise ValueError(f"Document with ID {document_id} not found.")

            # Idempotency check: if exact file already ingested for this doc, return it
            existing_ver = self.db.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id,
                DocumentVersion.file_sha256 == file_sha
            ).first()
            if existing_ver:
                return existing_ver, True

            # Find latest existing version
            latest_ver = self.db.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id
            ).order_by(DocumentVersion.version_no.desc()).first()
            
            version_no = (latest_ver.version_no + 1) if latest_ver else 1
            prev_doc_version = latest_ver

        # 2. Parse PDF via extraction engine
        parse_result = parse_pdf_document(pdf_path)
        new_ast_nodes = parse_result["nodes"]
        report = parse_result["parse_report"]

        # 3. Create DocumentVersion record
        doc_version = DocumentVersion(
            document_id=document_id,
            version_no=version_no,
            source_filename=pdf_path.name,
            file_sha256=file_sha,
            page_count=report["page_count"],
            parse_status=report["status"],
            parse_report=report,
            parent_version_id=prev_doc_version.id if prev_doc_version else None
        )
        self.db.add(doc_version)
        self.db.flush()

        # 4. Version Matching (if previous version exists)
        match_map = {}
        old_node_id_to_logical_id = {}
        if prev_doc_version:
            # Reconstruct previous version AST nodes
            prev_node_rows = self.db.query(NodeVersion).filter(
                NodeVersion.document_version_id == prev_doc_version.id
            ).all()

            old_ast_nodes = {}
            for r in prev_node_rows:
                old_node_id_to_logical_id[r.id] = r.logical_node_id
                dn = DocumentNode(
                    node_id=r.id,
                    section_number=r.section_number,
                    heading=r.heading,
                    level_declared=r.level_declared,
                    tree_depth=r.tree_depth,
                    parent_id=r.parent_node_version_id,
                    doc_order=r.doc_order,
                    page_start=r.page_start
                )
                dn.body_norm = r.body_norm
                dn.heading_norm = r.heading_norm
                dn.own_hash = r.own_hash
                dn.subtree_hash = r.subtree_hash
                old_ast_nodes[r.id] = dn

            matcher = VersionMatcher(v_old_nodes=old_ast_nodes, v_new_nodes=new_ast_nodes)
            match_map = matcher.match()

        # 5. Persist Logical Nodes and Node Versions
        ast_id_to_db_id = {}
        created_node_versions = []

        for ast_id, node in new_ast_nodes.items():
            match_info = match_map.get(ast_id)
            
            if match_info and not match_info["is_new_logical"]:
                # Re-use logical node ID from previous version
                prev_node_id = match_info["prev_node_id"]
                logical_id = old_node_id_to_logical_id[prev_node_id]
                change_status = match_info["change_status"]
                change_basis = match_info["change_basis"]
                match_score = match_info["match_score"]
            else:
                # First seen: create new logical node
                logical_node = LogicalNode(
                    document_id=document_id,
                    first_seen_version_id=doc_version.id,
                    canonical_number=node.section_number,
                    canonical_title=node.heading
                )
                self.db.add(logical_node)
                self.db.flush()
                logical_id = logical_node.id
                change_status = "added" if prev_doc_version else "unchanged"
                change_basis = "initial_ingest" if not prev_doc_version else "new_section"
                match_score = 1.0 if not prev_doc_version else 0.0
                prev_node_id = None

            nv = NodeVersion(
                logical_node_id=logical_id,
                document_version_id=doc_version.id,
                parent_node_version_id=None,  # updated in pass below
                section_number=node.section_number,
                heading=node.heading,
                heading_norm=node.heading_norm,
                level_declared=node.level_declared,
                tree_depth=node.tree_depth,
                doc_order=node.doc_order,
                page_start=node.page_start,
                page_end=node.page_end,
                body_text=node.body_text,
                body_norm=node.body_norm,
                blocks_json=node.blocks,
                own_hash=node.own_hash,
                subtree_hash=node.subtree_hash,
                flags_json=node.flags,
                change_status=change_status,
                change_basis=change_basis,
                match_score=match_score,
                prev_node_version_id=prev_node_id
            )
            self.db.add(nv)
            self.db.flush()
            ast_id_to_db_id[ast_id] = nv.id
            created_node_versions.append((nv, node))

        # Wire parent_node_version_id foreign keys
        for nv, node in created_node_versions:
            if node.parent_id and node.parent_id in ast_id_to_db_id:
                nv.parent_node_version_id = ast_id_to_db_id[node.parent_id]

            # Save cross-references
            for ref_str in node.references:
                ref_record = NodeReference(
                    from_node_version_id=nv.id,
                    raw_text=ref_str,
                    target_section_number=ref_str,
                    resolved_node_version_id=None
                )
                self.db.add(ref_record)

        self.db.commit()
        return doc_version, False
