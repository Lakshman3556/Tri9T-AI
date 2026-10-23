"""
Table Extraction Module (Section 5.4)
Uses PyMuPDF find_tables() geometry with cell-clipped word grouping to eliminate
comma/dash corruption inherent in PyMuPDF's default get_text inside cells.
"""
from typing import List, Dict, Any, Tuple
import fitz
from app.parser.normalize import normalize_text


def extract_clean_cell_text(page: fitz.Page, cell_rect: fitz.Rect) -> str:
    """
    Extracts clean text from a table cell by clipping words to the cell bbox,
    sorting lines top-to-bottom and words left-to-right.
    Fixes the PyMuPDF bug where '1 .5 seconds' or stray commas occur.
    """
    words = page.get_text("words", clip=cell_rect)
    if not words:
        return ""
    
    # words are tuples: (x0, y0, x1, y1, word_text, block_no, line_no, word_no)
    lines_dict = {}
    for w in words:
        line_key = (w[5], w[6])  # block_no, line_no
        if line_key not in lines_dict:
            lines_dict[line_key] = []
        lines_dict[line_key].append(w)
    
    # Sort lines by y0 of their first word
    sorted_lines = sorted(lines_dict.values(), key=lambda line_words: line_words[0][1])
    
    line_strings = []
    for line_words in sorted_lines:
        sorted_words = sorted(line_words, key=lambda w: w[0])  # sort by x0
        line_str = " ".join(w[4] for w in sorted_words)
        line_strings.append(line_str)
    
    combined = " ".join(line_strings)
    return normalize_text(combined)


def extract_tables_from_page(page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
    """
    Extracts all structured tables from a single PDF page with clean cell contents.
    Returns table blocks ready for AST attachment.
    """
    tables_found = page.find_tables()
    extracted_tables = []
    
    for t in tables_found.tables:
        raw_rows = []
        for row in t.rows:
            cell_texts = []
            for cell_bbox in row.cells:
                if cell_bbox is None:
                    cell_texts.append("")
                else:
                    rect = fitz.Rect(cell_bbox)
                    cell_text = extract_clean_cell_text(page, rect)
                    cell_texts.append(cell_text)
            raw_rows.append(cell_texts)
        
        if not raw_rows:
            continue
            
        header = raw_rows[0]
        data_rows = raw_rows[1:] if len(raw_rows) > 1 else []
        
        extracted_tables.append({
            "type": "table",
            "page": page_num,
            "bbox": list(t.bbox),
            "header": header,
            "rows": data_rows,
            "row_count": len(raw_rows),
            "col_count": len(header)
        })
        
    return extracted_tables


def is_inside_table(bbox: Tuple[float, float, float, float], table_bboxes: List[List[float]], tolerance: float = 2.0) -> bool:
    """Checks if a bounding box intersects with any table bounding box within tolerance."""
    bx0, by0, bx1, by1 = bbox
    for tx0, ty0, tx1, ty1 in table_bboxes:
        if not (bx1 < tx0 - tolerance or bx0 > tx1 + tolerance or by1 < ty0 - tolerance or by0 > ty1 + tolerance):
            return True
    return False
