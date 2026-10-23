"""
SQLAlchemy Relational Schema (Section 4)
Defines documents, document_versions, logical_nodes, node_versions,
node_references, selections, and selection_items.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, ForeignKey, JSON, Text, Boolean, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")
    logical_nodes = relationship("LogicalNode", back_populates="document", cascade="all, delete-orphan")
    selections = relationship("Selection", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_no = Column(Integer, nullable=False)
    source_filename = Column(String(255), nullable=False)
    file_sha256 = Column(String(64), nullable=False)
    page_count = Column(Integer, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    parse_status = Column(String(32), nullable=False, default="ok")  # ok, needs_review, failed
    parse_report = Column(JSON, nullable=False, default=dict)
    parent_version_id = Column(String(36), ForeignKey("document_versions.id"), nullable=True)

    document = relationship("Document", back_populates="versions")
    node_versions = relationship("NodeVersion", back_populates="document_version", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_doc_version_no"),
    )


class LogicalNode(Base):
    """
    Stable identity across document versions.
    node_id referenced by external APIs is this logical_node_id.
    """
    __tablename__ = "logical_nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    first_seen_version_id = Column(String(36), ForeignKey("document_versions.id"), nullable=False)
    canonical_number = Column(String(64), nullable=False)
    canonical_title = Column(String(255), nullable=False)

    document = relationship("Document", back_populates="logical_nodes")
    node_versions = relationship("NodeVersion", back_populates="logical_node", cascade="all, delete-orphan")


class NodeVersion(Base):
    """
    Immutable snapshot of a node in a specific document version.
    """
    __tablename__ = "node_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    logical_node_id = Column(String(36), ForeignKey("logical_nodes.id", ondelete="CASCADE"), nullable=False)
    document_version_id = Column(String(36), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    parent_node_version_id = Column(String(36), ForeignKey("node_versions.id"), nullable=True)
    
    section_number = Column(String(64), nullable=False)
    heading = Column(String(255), nullable=False)
    heading_norm = Column(String(255), nullable=False)
    level_declared = Column(Integer, nullable=False)
    tree_depth = Column(Integer, nullable=False)
    doc_order = Column(Integer, nullable=False)
    page_start = Column(Integer, nullable=False)
    page_end = Column(Integer, nullable=False)
    
    body_text = Column(Text, nullable=False, default="")
    body_norm = Column(Text, nullable=False, default="")
    blocks_json = Column(JSON, nullable=False, default=list)
    
    own_hash = Column(String(64), nullable=False)
    subtree_hash = Column(String(64), nullable=False)
    flags_json = Column(JSON, nullable=False, default=list)
    
    # Versioning diff status relative to previous version
    change_status = Column(String(32), nullable=False, default="unchanged")  # unchanged, modified, added, removed, renumbered, moved
    change_basis = Column(String(64), nullable=True)  # pass name e.g. exact_key, fuzzy, leftover
    match_score = Column(Float, nullable=True)
    prev_node_version_id = Column(String(36), ForeignKey("node_versions.id"), nullable=True)

    logical_node = relationship("LogicalNode", back_populates="node_versions")
    document_version = relationship("DocumentVersion", back_populates="node_versions")
    children = relationship("NodeVersion", foreign_keys=[parent_node_version_id])


class NodeReference(Base):
    __tablename__ = "node_references"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    from_node_version_id = Column(String(36), ForeignKey("node_versions.id", ondelete="CASCADE"), nullable=False)
    raw_text = Column(String(255), nullable=False)
    target_section_number = Column(String(64), nullable=False)
    resolved_node_version_id = Column(String(36), ForeignKey("node_versions.id"), nullable=True)


class Selection(Base):
    """
    Version-pinned collection of sections. Immutable once created.
    """
    __tablename__ = "selections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    fingerprint = Column(String(64), nullable=False)

    document = relationship("Document", back_populates="selections")
    items = relationship("SelectionItem", back_populates="selection", cascade="all, delete-orphan", order_by="SelectionItem.position")


class SelectionItem(Base):
    __tablename__ = "selection_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    selection_id = Column(String(36), ForeignKey("selections.id", ondelete="CASCADE"), nullable=False)
    node_version_id = Column(String(36), ForeignKey("node_versions.id", ondelete="CASCADE"), nullable=False)
    logical_node_id = Column(String(36), ForeignKey("logical_nodes.id"), nullable=False)
    pinned_hash = Column(String(64), nullable=False)
    position = Column(Integer, nullable=False)

    selection = relationship("Selection", back_populates="items")
    node_version = relationship("NodeVersion")
