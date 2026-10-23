"""
Text Normalization and Content Hashing Engine (Section 5.6)
Handles:
- Unicode NFKC normalization (replaces ligatures: fi -> fi, fl -> fl, ff -> ff)
- Non-breaking hyphens (U+2011, U+2010 -> '-')
- Whitespace collapsing across page breaks
- Content hashing (own_hash excludes section number so pure renumbering doesn't mark modified)
- Subtree hashing covering child hashes in reading order
"""
import re
import unicodedata
import hashlib
from typing import List, Dict, Any


def normalize_text(s: str) -> str:
    """Normalizes text for consistent comparison, searching, and hashing."""
    if not s:
        return ""
    # Unicode NFKC expands ligatures (\ufb01 -> fi, \ufb02 -> fl, \ufb00 -> ff)
    s = unicodedata.normalize("NFKC", s)
    # Map non-breaking and figure hyphens to standard ASCII hyphen
    s = s.replace("\u2011", "-").replace("\u2010", "-")
    # Collapse all whitespace sequences (including newlines and page break gaps) to single space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compute_sha256(content: str) -> str:
    """Returns hexadecimal SHA-256 digest of input string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_own_hash(heading_title: str, blocks: List[Dict[str, Any]]) -> str:
    """
    Computes own_hash for a node.
    Crucial design rule: Excludes section number (e.g. '2.1') so pure renumbering
    is recognized as 'renumbered' rather than 'modified'.
    """
    norm_title = normalize_text(heading_title)
    
    # Flatten blocks (paragraphs, lists, table rows) into canonical representation
    body_parts = []
    for block in blocks:
        b_type = block.get("type")
        if b_type == "paragraph":
            body_parts.append(normalize_text(block.get("text", "")))
        elif b_type == "list":
            for item in block.get("items", []):
                if isinstance(item, dict):
                    body_parts.append(f"{item.get('marker', '')} {normalize_text(item.get('text', ''))}".strip())
                else:
                    body_parts.append(normalize_text(str(item)))
        elif b_type == "table":
            # Canonicalize table by sorting/joining row cells
            rows = block.get("rows", [])
            for row in rows:
                body_parts.append(" | ".join(normalize_text(cell) for cell in row))
    
    canonical_body = " ".join(part for part in body_parts if part)
    combined = f"{norm_title}\n{canonical_body}"
    return compute_sha256(combined)


def compute_subtree_hash(own_hash: str, children_subtree_hashes: List[str]) -> str:
    """Computes recursive subtree hash combining node's own hash with children in doc_order."""
    combined = own_hash + "".join(children_subtree_hashes)
    return compute_sha256(combined)
