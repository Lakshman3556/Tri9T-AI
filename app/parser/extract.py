"""
Document Extraction Pipeline (Section 5.1)
Coordinates all extraction stages:
Stage A: Raw Line extraction
Stage B: Ruled table extraction & bbox isolation
Stage C: Line classification (Title, Heading, List, Body)
Stage D: Hierarchy tree construction & cross-page continuation (Tables inserted at y0)
Stage E: Content hashing (own_hash, subtree_hash)
Stage F: Invariant verification
Stage G: Parse report generation
Stage H: OCR cross-check
"""
from pathlib import Path
from typing import Dict, Any, List
import fitz

from app.parser.tables import extract_tables_from_page, is_inside_table
from app.parser.classify import LineClassifier
from app.parser.tree import HierarchyBuilder
from app.parser.validate import InvariantValidator, tokenize_words
from app.parser.ocr_check import run_ocr_cross_check
from app.parser.normalize import normalize_text


def parse_pdf_document(pdf_path: Path, run_ocr: bool = False) -> Dict[str, Any]:
    """
    Parses a CT-200 manual PDF into a hierarchical node tree with parse_report and invariants.
    """
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    
    # 1. Determine margin dynamically from page set
    all_x0s = []
    for page in doc:
        t_dict = page.get_text("dict")
        for b in t_dict.get("blocks", []):
            if b.get("type") == 0:
                for l in b.get("lines", []):
                    all_x0s.append(round(l["bbox"][0], 1))
    margin_x0 = min(all_x0s) if all_x0s else 33.0

    classifier = LineClassifier(margin_x0=margin_x0)
    builder = HierarchyBuilder()

    all_page_words: List[str] = []
    native_page_texts: List[str] = []
    detected_table_count = 0
    detected_heading_count = 0
    title_collected = []

    for p_idx, page in enumerate(doc):
        page_num = p_idx + 1
        native_page_texts.append(page.get_text())

        # Stage B: Extract tables first for this page
        page_tables = extract_tables_from_page(page, page_num)
        detected_table_count += len(page_tables)
        table_bboxes = [t["bbox"] for t in page_tables]

        # Extract non-table lines with geometry
        page_items = []
        # Add tables with their y0
        for tbl in page_tables:
            page_items.append({
                "kind": "table",
                "y0": tbl["bbox"][1],
                "payload": tbl
            })

        t_dict = page.get_text("dict")
        for block in t_dict.get("blocks", []):
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                    max_size = max((span.get("size", 0.0) for span in line.get("spans", [])), default=0.0)
                    is_bold = any(("Bold" in span.get("font", "") or (span.get("flags", 0) & 16)) for span in line.get("spans", []))
                    bbox = tuple(line.get("bbox", (0, 0, 0, 0)))

                    if not line_text.strip():
                        continue

                    # If line is inside a table, exclude it from line stream
                    if is_inside_table(bbox, table_bboxes):
                        continue

                    norm_line = normalize_text(line_text)
                    all_page_words.extend(tokenize_words(norm_line))

                    page_items.append({
                        "kind": "line",
                        "y0": bbox[1],
                        "payload": {
                            "text": norm_line,
                            "x0": round(bbox[0], 2),
                            "y0": round(bbox[1], 2),
                            "size": round(max_size, 2),
                            "bold": is_bold,
                            "bbox": bbox,
                            "page": page_num
                        }
                    })

        # Sort all items on page strictly by y0
        page_items.sort(key=lambda item: item["y0"])

        # Process stream in physical vertical order
        for item in page_items:
            if item["kind"] == "table":
                builder.add_table_block(item["payload"])
            elif item["kind"] == "line":
                line_obj = item["payload"]
                classified = classifier.classify_line(line_obj, is_in_table=False)
                c_type = classified["type"]

                if c_type == "TITLE":
                    title_collected.append(classified["text"])
                elif c_type == "HEADING":
                    detected_heading_count += 1
                    if not builder.root_node and title_collected:
                        builder.set_title(" ".join(title_collected), page=1)

                    builder.add_heading(
                        section_number=classified["section_number"],
                        heading_title=classified["heading_title"],
                        level_declared=classified["level_declared"],
                        page=page_num,
                        size_mismatch=classified.get("size_mismatch", False)
                    )
                elif c_type == "LIST_ITEM":
                    builder.add_list_item(classified["marker"], classified["item_text"], page=page_num)
                elif c_type == "LIST_CONT":
                    builder.append_list_cont(classified["text"], page=page_num)
                elif c_type == "BODY":
                    builder.add_paragraph_line(classified["text"], page=page_num)

    if not builder.root_node and title_collected:
        builder.set_title(" ".join(title_collected), page=1)

    # Stage E & F: Finalize tree (render bodies, hashes, duplicate titles)
    builder.finalize_tree()

    # Stage G: Invariant Validation
    validator = InvariantValidator(
        nodes=builder.nodes,
        page_words=all_page_words,
        expected_table_count=detected_table_count,
        expected_heading_count=detected_heading_count
    )
    is_valid, hard_failures, soft_warnings = validator.validate_all()

    # Stage H: OCR Cross-Check
    ocr_report = run_ocr_cross_check(doc, native_page_texts) if run_ocr else {
        "status": "skipped",
        "reason": "OCR cross-check not requested for deterministic run"
    }

    parse_status = "ok"
    if not is_valid:
        parse_status = "failed"
    elif any("disagreement" in w.lower() for w in soft_warnings) or ocr_report.get("warnings"):
        parse_status = "needs_review"

    parse_report = {
        "status": parse_status,
        "is_valid": is_valid,
        "page_count": page_count,
        "node_count": len(builder.nodes),
        "hard_failures": hard_failures,
        "warnings": soft_warnings,
        "ocr": ocr_report
    }

    return {
        "root_id": builder.root_node.id if builder.root_node else None,
        "nodes": builder.nodes,
        "parse_report": parse_report
    }
