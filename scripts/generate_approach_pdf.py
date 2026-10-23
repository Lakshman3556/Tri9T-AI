"""
Compile docs/APPROACH.md into a submission-ready PDF document:
CT200_Assignment_Approach_Document_Lakshman.pdf
"""
from pathlib import Path
import fitz

ROOT_DIR = Path(__file__).parent.parent
MD_PATH = ROOT_DIR / "docs" / "APPROACH.md"
PDF_PATH = ROOT_DIR / "CT200_Assignment_Approach_Document_Lakshman.pdf"


def generate_approach_pdf():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()

    doc = fitz.open()
    
    # Page dimensions: A4 (595.3 x 841.9 pt), margin = 45 pt
    page_width = 595.3
    page_height = 841.9
    margin = 45.0
    usable_width = page_width - 2 * margin

    page = doc.new_page(width=page_width, height=page_height)
    cursor_y = margin

    def check_page_space(needed_pt: float):
        nonlocal page, cursor_y
        if cursor_y + needed_pt > page_height - margin:
            # Draw footer on existing page
            page.draw_line(fitz.Point(margin, page_height - 35), fitz.Point(page_width - margin, page_height - 35), color=(0.7, 0.7, 0.7), width=0.5)
            page.insert_text(fitz.Point(margin, page_height - 20), "CardioTrack CT-200 QA API — Approach Document & Decision Log | Candidate: Lakshman", fontsize=8, color=(0.4, 0.4, 0.4))
            p_num = f"Page {len(doc)}"
            page.insert_text(fitz.Point(page_width - margin - 35, page_height - 20), p_num, fontsize=8, color=(0.4, 0.4, 0.4))
            
            # Start new page
            page = doc.new_page(width=page_width, height=page_height)
            cursor_y = margin + 15
            # Header on new page
            page.draw_line(fitz.Point(margin, margin + 5), fitz.Point(page_width - margin, margin + 5), color=(0.8, 0.8, 0.8), width=0.5)
            page.insert_text(fitz.Point(margin, margin), "AffineSurge / Tri9T AI Engineering Technical Assignment Submission", fontsize=8, color=(0.5, 0.5, 0.5))

    lines = md_text.splitlines()

    for line in lines:
        line_str = line.strip()

        if not line_str:
            cursor_y += 5
            continue

        # Level 1 Heading (# Title)
        if line.startswith("# "):
            check_page_space(40)
            title_text = line[2:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 26)
            page.insert_textbox(rect, title_text, fontsize=15, fontname="helv", color=(0.08, 0.2, 0.45))
            cursor_y += 30
            # Underline
            page.draw_line(fitz.Point(margin, cursor_y - 4), fitz.Point(margin + usable_width, cursor_y - 4), color=(0.1, 0.35, 0.7), width=1.5)
            cursor_y += 6

        # Level 2 Heading (## Section)
        elif line.startswith("## "):
            check_page_space(30)
            h2_text = line[3:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 20)
            page.insert_textbox(rect, h2_text, fontsize=12, fontname="helv", color=(0.12, 0.3, 0.6))
            cursor_y += 24

        # Level 3 Heading (### Sub-section / Question)
        elif line.startswith("### "):
            check_page_space(24)
            h3_text = line[4:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 16)
            page.insert_textbox(rect, h3_text, fontsize=10, fontname="helv", color=(0.15, 0.25, 0.4))
            cursor_y += 18

        # Table rows (| ... |)
        elif line_str.startswith("|"):
            if "---" in line_str:
                continue
            cells = [c.strip() for c in line_str.split("|")[1:-1]]
            cell_text = "   |   ".join(cells)
            check_page_space(16)
            rect = fitz.Rect(margin + 5, cursor_y, margin + usable_width, cursor_y + 14)
            page.insert_textbox(rect, cell_text, fontsize=8, fontname="helv", color=(0.2, 0.2, 0.2))
            cursor_y += 14

        # Bullet points
        elif line_str.startswith("* ") or line_str.startswith("- "):
            bullet_text = "• " + line_str[2:].strip()
            lines_est = max(1, len(bullet_text) // 90 + 1)
            needed = lines_est * 12 + 4
            check_page_space(needed)
            rect = fitz.Rect(margin + 8, cursor_y, margin + usable_width, cursor_y + needed)
            page.insert_textbox(rect, bullet_text, fontsize=8.5, fontname="helv", color=(0.15, 0.15, 0.15))
            cursor_y += needed

        # Code block
        elif line_str.startswith("```"):
            cursor_y += 4

        # Normal Paragraphs
        else:
            lines_est = max(1, len(line_str) // 95 + 1)
            needed = lines_est * 12 + 4
            check_page_space(needed)
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + needed)
            # Question highlights in Decision Log
            text_color = (0.05, 0.15, 0.35) if line_str.startswith("**Lakshman:**") else (0.2, 0.2, 0.2)
            page.insert_textbox(rect, line_str, fontsize=8.5, fontname="helv", color=text_color)
            cursor_y += needed

    # Final footer
    page.draw_line(fitz.Point(margin, page_height - 35), fitz.Point(page_width - margin, page_height - 35), color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_text(fitz.Point(margin, page_height - 20), "CardioTrack CT-200 QA API — Approach Document & Decision Log | Candidate: Lakshman", fontsize=8, color=(0.4, 0.4, 0.4))
    page.insert_text(fitz.Point(page_width - margin - 35, page_height - 20), f"Page {len(doc)}", fontsize=8, color=(0.4, 0.4, 0.4))

    doc.save(PDF_PATH)
    print(f"Successfully compiled Approach Document into {PDF_PATH} ({len(doc)} pages)!")


if __name__ == "__main__":
    generate_approach_pdf()
