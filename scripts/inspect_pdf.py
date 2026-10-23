"""
PDF Inspection Script: Inspects CT-200 manual PDFs for physical properties,
fonts, font sizes, margins, line pitch, vector drawings, and tables.
Feeds data directly into docs/DEBUG_LOG.md.
"""
import sys
from pathlib import Path
from collections import Counter, defaultdict
import fitz  # PyMuPDF


def inspect_file(pdf_path: Path):
    print(f"\n{'='*70}\nINSPECTING: {pdf_path.name}\n{'='*70}")
    doc = fitz.open(pdf_path)
    print(f"Total pages: {len(doc)}")
    
    font_counter = Counter()
    size_counter = Counter()
    min_x0_per_page = {}
    lines_per_page = defaultdict(list)
    total_drawings = 0
    total_images = 0

    for page_idx, page in enumerate(doc):
        rect = page.rect
        drawings = page.get_drawings()
        images = page.get_images()
        tables = page.find_tables()
        total_drawings += len(drawings)
        total_images += len(images)

        text_dict = page.get_text("dict")
        page_x0s = []
        
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # text block
                for line in block.get("lines", []):
                    line_text = ""
                    max_size = 0.0
                    is_bold = False
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                        sz = round(span.get("size", 0.0), 2)
                        font = span.get("font", "")
                        flags = span.get("flags", 0)
                        font_counter[font] += 1
                        size_counter[sz] += 1
                        if sz > max_size:
                            max_size = sz
                        if "Bold" in font or (flags & 16):
                            is_bold = True
                    
                    line_text_stripped = line_text.strip()
                    if line_text_stripped:
                        x0 = round(line["bbox"][0], 2)
                        y0 = round(line["bbox"][1], 2)
                        page_x0s.append(x0)
                        lines_per_page[page_idx].append({
                            "text": line_text_stripped,
                            "x0": x0,
                            "y0": y0,
                            "size": max_size,
                            "bold": is_bold,
                            "bbox": line["bbox"]
                        })

        min_x0 = min(page_x0s) if page_x0s else 0.0
        min_x0_per_page[page_idx] = min_x0

        print(f"Page {page_idx+1}: size={rect.width}x{rect.height} pt, "
              f"lines={len(lines_per_page[page_idx])}, drawings={len(drawings)}, "
              f"images={len(images)}, tables_found={len(tables.tables)}, min_x0={min_x0}")

        if tables.tables:
            for t_idx, t in enumerate(tables.tables):
                print(f"   Table {t_idx+1}: bbox={t.bbox}, row_count={t.row_count}, col_count={t.col_count}")

    print("\n--- Font Distribution ---")
    for font, count in font_counter.most_common():
        print(f"  {font}: {count} spans")

    print("\n--- Font Size Distribution ---")
    for sz, count in size_counter.most_common():
        print(f"  {sz} pt: {count} spans")

    print(f"\nTotal Embedded Images across document: {total_images}")
    print(f"Total Vector Drawings across document: {total_drawings}")

    return {
        "pages": len(doc),
        "total_images": total_images,
        "total_drawings": total_drawings,
        "fonts": dict(font_counter),
        "sizes": dict(size_counter),
        "lines": lines_per_page
    }


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"
    
    v1_path = data_dir / "ct200_manual.pdf"
    v2_path = data_dir / "ct200_manual_v2.pdf"

    if not v1_path.exists():
        print(f"Error: {v1_path} not found")
        sys.exit(1)

    print("Beginning PDF inspection for CT-200 manual v1 and v2...")
    v1_info = inspect_file(v1_path)
    if v2_path.exists():
        v2_info = inspect_file(v2_path)
