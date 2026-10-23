"""
Hierarchy Reconstruction Engine (Sections 5.3, 5.5, 5.6)
Builds a persistent document AST from classified lines and table blocks.
Tracks parent/child hierarchy via numeric prefix matching, handles irregularities:
- I1: Multi-line title merge
- I2: Heading size mismatch flag
- I3: Skipped level (2.1 -> 2.1.1.1) with level_gap flag
- I4: Out-of-order siblings (3.4 before 3.3) with out_of_order flag
- I5: Duplicate titles (4.2 and 7.1 Error Codes) with duplicate_title flag
- I7: Cross references extraction (3.3 -> 2.1, 4.3; 7.1 -> 4.2)
- I10/I11: Page-break joins and split_across_pages flag
- I12: Heading-only parent preservation
"""
import re
import uuid
from typing import List, Dict, Any, Optional
from app.parser.normalize import normalize_text, compute_own_hash, compute_subtree_hash

REF_PATTERN = re.compile(r"(?:see\s+|Section\s+)(\d+(?:\.\d+)*(?:,\s*\d+(?:\.\d+)*)*)", re.IGNORECASE)


class DocumentNode:
    def __init__(
        self,
        node_id: str,
        section_number: str,
        heading: str,
        level_declared: int,
        tree_depth: int,
        parent_id: Optional[str] = None,
        doc_order: int = 0,
        page_start: int = 1
    ):
        self.id = node_id
        self.section_number = section_number
        self.heading = heading
        self.heading_norm = normalize_text(heading)
        self.level_declared = level_declared
        self.tree_depth = tree_depth
        self.parent_id = parent_id
        self.doc_order = doc_order
        self.page_start = page_start
        self.page_end = page_start
        
        self.blocks: List[Dict[str, Any]] = []
        self.children_ids: List[str] = []
        self.flags: List[str] = []
        self.references: List[str] = []
        
        self.own_hash: str = ""
        self.subtree_hash: str = ""
        self.body_text: str = ""
        self.body_norm: str = ""

    def render_body(self):
        """Renders body_text (display) and body_norm (normalized for search & diffing)."""
        rendered_blocks = []
        for b in self.blocks:
            b_type = b.get("type")
            if b_type == "paragraph":
                rendered_blocks.append(b.get("text", ""))
            elif b_type == "list":
                items = [f"{item['marker']} {item['text']}" for item in b.get("items", [])]
                rendered_blocks.append("\n".join(items))
            elif b_type == "table":
                rows_text = []
                header = b.get("header", [])
                if header:
                    rows_text.append(" | ".join(header))
                for row in b.get("rows", []):
                    rows_text.append(" | ".join(row))
                rendered_blocks.append("\n".join(rows_text))

        self.body_text = "\n\n".join(rendered_blocks).strip()
        self.body_norm = normalize_text(self.body_text)

        # Extract cross-references in text
        for match in REF_PATTERN.finditer(self.body_text):
            ref_group = match.group(1)
            for part in ref_group.split(","):
                clean_ref = part.strip()
                if clean_ref and clean_ref not in self.references:
                    self.references.append(clean_ref)


class HierarchyBuilder:
    def __init__(self):
        self.nodes: Dict[str, DocumentNode] = {}
        self.doc_order_counter = 0
        self.root_node: Optional[DocumentNode] = None
        self.current_node: Optional[DocumentNode] = None
        self.number_to_node_id: Dict[str, str] = {}
        self.title_lines: List[str] = []

    def set_title(self, title_text: str, page: int = 1):
        clean_title = normalize_text(title_text)
        root_id = str(uuid.uuid4())
        self.root_node = DocumentNode(
            node_id=root_id,
            section_number="0",
            heading=clean_title,
            level_declared=0,
            tree_depth=0,
            parent_id=None,
            doc_order=0,
            page_start=page
        )
        self.nodes[root_id] = self.root_node
        self.current_node = self.root_node
        self.number_to_node_id["0"] = root_id

    def add_heading(
        self,
        section_number: str,
        heading_title: str,
        level_declared: int,
        page: int,
        size_mismatch: bool = False
    ) -> DocumentNode:
        self.doc_order_counter += 1
        node_id = str(uuid.uuid4())
        
        # Determine parent by deepest existing dotted prefix
        # e.g., for 2.1.1.1: check 2.1.1, then 2.1, then 2, then 0 (root)
        parts = section_number.split(".")
        parent_id = None
        level_gap = False
        
        for k in range(len(parts) - 1, 0, -1):
            candidate_num = ".".join(parts[:k])
            if candidate_num in self.number_to_node_id:
                parent_id = self.number_to_node_id[candidate_num]
                if k < len(parts) - 1:
                    level_gap = True
                break
        
        if not parent_id and self.root_node:
            parent_id = self.root_node.id
            if len(parts) > 1:
                level_gap = True

        parent_node = self.nodes.get(parent_id) if parent_id else None
        tree_depth = (parent_node.tree_depth + 1) if parent_node else 1

        node = DocumentNode(
            node_id=node_id,
            section_number=section_number,
            heading=normalize_text(heading_title),
            level_declared=level_declared,
            tree_depth=tree_depth,
            parent_id=parent_id,
            doc_order=self.doc_order_counter,
            page_start=page
        )

        if size_mismatch:
            node.flags.append("size_mismatch")
        if level_gap:
            node.flags.append("level_gap")

        # Check for non-monotonic sibling order (e.g. 3.4 appearing before 3.3)
        if parent_node:
            for sibling_id in parent_node.children_ids:
                sibling = self.nodes[sibling_id]
                # Compare dot parts if same depth
                sib_parts = sibling.section_number.split(".")
                curr_parts = section_number.split(".")
                if len(sib_parts) == len(curr_parts) and sib_parts[:-1] == curr_parts[:-1]:
                    try:
                        if int(curr_parts[-1]) < int(sib_parts[-1]):
                            node.flags.append("out_of_order")
                    except ValueError:
                        pass
            parent_node.children_ids.append(node_id)

        self.nodes[node_id] = node
        self.number_to_node_id[section_number] = node_id
        self.current_node = node
        return node

    def add_paragraph_line(self, text: str, page: int):
        if not self.current_node:
            return
        
        self.current_node.page_end = max(self.current_node.page_end, page)
        clean_text = text.strip()
        if not clean_text:
            return

        blocks = self.current_node.blocks
        # If previous block is a paragraph, determine if appending across lines or page
        if blocks and blocks[-1]["type"] == "paragraph":
            prev_block = blocks[-1]
            if page > prev_block.get("last_page", page):
                if "split_across_pages" not in self.current_node.flags:
                    self.current_node.flags.append("split_across_pages")
            prev_block["text"] += " " + clean_text
            prev_block["last_page"] = page
        else:
            blocks.append({
                "type": "paragraph",
                "text": clean_text,
                "first_page": page,
                "last_page": page
            })

    def add_list_item(self, marker: str, text: str, page: int):
        if not self.current_node:
            return
        
        self.current_node.page_end = max(self.current_node.page_end, page)
        blocks = self.current_node.blocks
        if blocks and blocks[-1]["type"] == "list":
            blocks[-1]["items"].append({"marker": marker, "text": text.strip()})
        else:
            blocks.append({
                "type": "list",
                "items": [{"marker": marker, "text": text.strip()}]
            })

    def append_list_cont(self, text: str, page: int):
        if not self.current_node:
            return
        self.current_node.page_end = max(self.current_node.page_end, page)
        blocks = self.current_node.blocks
        if blocks and blocks[-1]["type"] == "list" and blocks[-1]["items"]:
            blocks[-1]["items"][-1]["text"] += " " + text.strip()

    def add_table_block(self, table_dict: Dict[str, Any]):
        if not self.current_node:
            return
        self.current_node.page_end = max(self.current_node.page_end, table_dict["page"])
        self.current_node.blocks.append(table_dict)

    def finalize_tree(self):
        """Computes duplicate_title flags, body texts, own_hash and recursive subtree_hash."""
        # 1. Detect duplicate titles
        title_occurrences: Dict[str, List[DocumentNode]] = {}
        for node in self.nodes.values():
            if node.level_declared > 0:
                title_occurrences.setdefault(node.heading_norm, []).append(node)
                
        for norm_title, node_list in title_occurrences.items():
            if len(node_list) > 1:
                for n in node_list:
                    if "duplicate_title" not in n.flags:
                        n.flags.append("duplicate_title")

        # 2. Render bodies and compute own_hash
        for node in self.nodes.values():
            node.render_body()
            node.own_hash = compute_own_hash(node.heading, node.blocks)

        # 3. Post-order traversal for subtree_hash
        def compute_node_subtree_hash(node_id: str) -> str:
            node = self.nodes[node_id]
            child_hashes = [compute_node_subtree_hash(cid) for cid in node.children_ids]
            node.subtree_hash = compute_subtree_hash(node.own_hash, child_hashes)
            return node.subtree_hash

        if self.root_node:
            compute_node_subtree_hash(self.root_node.id)
