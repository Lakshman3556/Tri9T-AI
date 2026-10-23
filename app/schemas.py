"""
Pydantic Schemas for API Requests and Responses (FastAPI + Pydantic v2)
"""
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class DocumentCreate(BaseModel):
    name: str = "CardioTrack CT-200 Manual"


class DocumentResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class VersionSummary(BaseModel):
    id: str
    document_id: str
    version_no: int
    source_filename: str
    file_sha256: str
    page_count: int
    ingested_at: datetime
    parse_status: str
    warning_count: int
    added_count: int
    modified_count: int
    unchanged_count: int


class NodeSummary(BaseModel):
    node_id: str  # logical id
    node_version_id: str
    section_number: str
    heading: str
    level_declared: int
    tree_depth: int
    doc_order: int
    page_start: int
    page_end: int
    own_hash: str
    flags: List[str] = []


class NodeDetail(NodeSummary):
    body_text: str
    body_norm: str
    blocks: List[Dict[str, Any]] = []
    subtree_hash: str
    parent_node_id: Optional[str] = None
    children_node_ids: List[str] = []
    references: List[str] = []


class NodeChangeResponse(BaseModel):
    logical_node_id: str
    section_number: str
    heading: str
    changed: bool
    status: str  # unchanged, modified, added, removed, renumbered
    own_changed: bool
    subtree_changed: bool
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
    significance: Literal["material", "wording", "none"]
    diff: Dict[str, Any]
    referenced_nodes_changed: List[str] = []


class SearchResultItem(BaseModel):
    node_id: str
    node_version_id: str
    version_no: int
    section_number: str
    heading: str
    snippet: str
    score: float = 1.0


class SelectionItemInput(BaseModel):
    node_id: str  # logical node id
    version: Optional[int] = None  # defaults to latest active version


class SelectionCreate(BaseModel):
    name: str
    items: List[SelectionItemInput]


class SelectionItemOutput(BaseModel):
    node_id: str  # logical node id
    node_version_id: str  # pinned version
    version: int
    section_number: str
    heading: str
    pinned_hash: str
    position: int


class SelectionResponse(BaseModel):
    selection_id: str
    name: str
    document_id: str
    fingerprint: str
    created_at: datetime
    items: List[SelectionItemOutput]
