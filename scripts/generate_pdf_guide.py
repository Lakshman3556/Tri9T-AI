"""
Generate PDF Interview Guide
Reads docs/INTERVIEW_PREP.md and renders a formatted PDF document:
CT200_Interview_Preparation_Guide.pdf using PyMuPDF.
"""
import re
from pathlib import Path
import fitz

ROOT_DIR = Path(__file__).parent.parent
MD_PATH = ROOT_DIR / "docs" / "INTERVIEW_PREP.md"
PDF_PATH = ROOT_DIR / "CT200_Interview_Preparation_Guide.pdf"


def create_pdf_from_markdown():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()

    doc = fitz.open()
    
    # Page setup: A4 (595.3 x 841.9 pt), margins = 45 pt
    page_width = 595.3
    page_height = 841.9
    margin = 45.0
    usable_width = page_width - 2 * margin
    usable_height = page_height - 2 * margin

    lines = md_text.splitlines()

    page = doc.new_page(width=page_width, height=page_height)
    cursor_y = margin

    def check_page_space(needed_pt: float):
        nonlocal page, cursor_y
        if cursor_y + needed_pt > page_height - margin:
            # Draw footer on current page
            page.draw_line(fitz.Point(margin, page_height - 35), fitz.Point(page_width - margin, page_height - 35), color=(0.7, 0.7, 0.7), width=0.5)
            page.insert_text(fitz.Point(margin, page_height - 20), "CardioTrack CT-200 QA API — Candidate Interview Guide (Lakshman)", fontsize=8, color=(0.4, 0.4, 0.4))
            p_num = f"Page {len(doc)}"
            page.insert_text(fitz.Point(page_width - margin - 35, page_height - 20), p_num, fontsize=8, color=(0.4, 0.4, 0.4))
            
            page = doc.new_page(width=page_width, height=page_height)
            cursor_y = margin + 15
            # Header on new page
            page.draw_line(fitz.Point(margin, margin + 5), fitz.Point(page_width - margin, margin + 5), color=(0.8, 0.8, 0.8), width=0.5)
            page.insert_text(fitz.Point(margin, margin), "AffineSurge / Tri9T AI Engineering Technical Assignment", fontsize=8, color=(0.5, 0.5, 0.5))

    for line in lines:
        line_str = line.strip()

        if not line_str:
            cursor_y += 6
            continue

        # Level 1 Heading (# Title)
        if line.startswith("# "):
            check_page_space(38)
            title_text = line[2:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 28)
            page.insert_textbox(rect, title_text, fontsize=16, fontname="helv", color=(0.08, 0.2, 0.45))
            cursor_y += 32
            # Decorative underline
            page.draw_line(fitz.Point(margin, cursor_y - 4), fitz.Point(margin + usable_width, cursor_y - 4), color=(0.1, 0.35, 0.7), width=1.5)
            cursor_y += 6

        # Level 2 Heading (## Subtitle)
        elif line.startswith("## "):
            check_page_space(30)
            h2_text = line[3:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 22)
            page.insert_textbox(rect, h2_text, fontsize=13, fontname="helv", color=(0.12, 0.3, 0.6))
            cursor_y += 24

        # Level 3 Heading (### Section / Question)
        elif line.startswith("### "):
            check_page_space(24)
            h3_text = line[4:].strip()
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + 18)
            page.insert_textbox(rect, h3_text, fontsize=10.5, fontname="helv", color=(0.15, 0.25, 0.4))
            cursor_y += 20

        # Bullet points
        elif line.startswith("* ") or line.startswith("- "):
            bullet_text = "• " + line[2:].strip()
            # Estimate height based on length
            lines_est = max(1, len(bullet_text) // 85 + 1)
            needed = lines_est * 13 + 4
            check_page_space(needed)
            rect = fitz.Rect(margin + 10, cursor_y, margin + usable_width, cursor_y + needed)
            page.insert_textbox(rect, bullet_text, fontsize=9, fontname="helv", color=(0.15, 0.15, 0.15))
            cursor_y += needed

        # Code block marker
        elif line.startswith("```"):
            cursor_y += 4

        # Standard Paragraph
        else:
            lines_est = max(1, len(line_str) // 90 + 1)
            needed = lines_est * 13 + 4
            check_page_space(needed)
            rect = fitz.Rect(margin, cursor_y, margin + usable_width, cursor_y + needed)
            # Differentiate Answer / Bold highlights
            text_color = (0.05, 0.1, 0.25) if "Answer:" in line_str or "**Answer:**" in line_str else (0.2, 0.2, 0.2)
            page.insert_textbox(rect, line_str, fontsize=9, fontname="helv", color=text_color)
            cursor_y += needed

    # Final page footer
    page.draw_line(fitz.Point(margin, page_height - 35), fitz.Point(page_width - margin, page_height - 35), color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_text(fitz.Point(margin, page_height - 20), "CardioTrack CT-200 QA API — Candidate Interview Guide (Lakshman)", fontsize=8, color=(0.4, 0.4, 0.4))
    page.insert_text(fitz.Point(page_width - margin - 35, page_height - 20), f"Page {len(doc)}", fontsize=8, color=(0.4, 0.4, 0.4))

    doc.save(PDF_PATH)
    print(f"Successfully generated {PDF_PATH} ({len(doc)} pages)!")


if __name__ == "__main__":
    create_pdf_from_markdown()
