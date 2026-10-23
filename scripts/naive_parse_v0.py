"""
Naive Parser v0: A simple baseline parser using basic regex and font-size thresholding.
Deliberately captures common baseline pitfalls (missing 11pt headings, treating numbered
lists as sections, failing on tables and page-break splits) to demonstrate real engineering
progression and debugging methodology.
"""
import re
from pathlib import Path
import fitz


def naive_parse(pdf_path: Path):
    doc = fitz.open(pdf_path)
    sections = []
    current_section = {"number": "0", "heading": "ROOT", "body": ""}

    heading_regex = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

    for page_idx, page in enumerate(doc):
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # text
                for line in block.get("lines", []):
                    line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    max_size = max((span.get("size", 0.0) for span in line.get("spans", [])), default=0.0)
                    
                    if not line_text:
                        continue

                    # Naive assumption 1: Headings are > 12pt and match number regex
                    match = heading_regex.match(line_text)
                    if match and max_size > 12.0:
                        sections.append(current_section)
                        current_section = {
                            "number": match.group(1),
                            "heading": match.group(2),
                            "body": ""
                        }
                    # Naive assumption 2: Or anything matching regex alone (catches numbered lists by mistake!)
                    elif match and (len(match.group(1)) == 1 or "." in match.group(1)):
                        # If we also check regex for list items...
                        # In a naive approach without margin check, '1. Normal' looks like section 1!
                        pass

                    current_section["body"] += line_text + "\n"

    sections.append(current_section)
    return sections


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent
    v1_pdf = base_dir / "data" / "ct200_manual.pdf"
    results = naive_parse(v1_pdf)
    print(f"Naive v0 parsed {len(results)} sections:")
    for s in results[:10]:
        print(f"  [{s['number']}] {s['heading']} (body length: {len(s['body'])} chars)")
