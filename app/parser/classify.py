"""
Line Classification Engine (Section 5.2)
Implements precise line classification rules:
- TITLE: size >= 20 and bold, before first HEADING (merges multi-line title I1)
- HEADING: bold AND matches HEAD_RE AND x0 <= margin + 3 AND not inside table bbox
- LIST_ITEM: NOT bold AND matches list regex AND x0 > margin + 5
- LIST_CONT: NOT bold, indented, no marker, follows LIST_ITEM/LIST_CONT (I14)
- BODY: everything else
"""
import re
from typing import Dict, Any, Optional

HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
LIST_MARKER_RE = re.compile(r"^(\d+[.)]|[-*\u2022])\s+(.+)$")


class LineClassifier:
    def __init__(self, margin_x0: float = 33.0):
        self.margin_x0 = margin_x0
        self.seen_first_heading = False
        self.prev_line_type: Optional[str] = None

    def classify_line(self, line: Dict[str, Any], is_in_table: bool) -> Dict[str, Any]:
        """
        Classifies a line dictionary:
        {text, x0, y0, size, bold, bbox, page}
        Returns line annotated with classification type and metadata.
        """
        if is_in_table:
            self.prev_line_type = "TABLE_CELL"
            return {**line, "type": "TABLE_CELL"}

        text = line["text"].strip()
        bold = line["bold"]
        size = line["size"]
        x0 = line["x0"]

        # Rule 1: TITLE (22pt bold lines before first heading)
        if not self.seen_first_heading and size >= 20.0 and bold:
            self.prev_line_type = "TITLE"
            return {**line, "type": "TITLE"}

        # Rule 2: HEADING (bold, matches numbering regex, at left margin, not in table)
        head_match = HEAD_RE.match(text)
        if bold and head_match and (x0 <= self.margin_x0 + 3.0):
            self.seen_first_heading = True
            section_number = head_match.group(1).rstrip(".")
            heading_title = head_match.group(2).strip()
            level_declared = len(section_number.split("."))

            # Flag size_mismatch if font size does not match standard hierarchy
            # Standard: L1 = 16.5, L2 = 12.87. Anomaly: 3.2 and 2.1.1.1 are 11.0 pt
            size_mismatch = (level_declared == 2 and size < 12.0) or (level_declared > 2 and size < 11.5)

            self.prev_line_type = "HEADING"
            return {
                **line,
                "type": "HEADING",
                "section_number": section_number,
                "heading_title": heading_title,
                "level_declared": level_declared,
                "size_mismatch": size_mismatch
            }

        # Rule 3: LIST_ITEM (not bold, indented, matches list marker)
        list_match = LIST_MARKER_RE.match(text)
        if not bold and list_match and (x0 > self.margin_x0 + 5.0):
            self.prev_line_type = "LIST_ITEM"
            return {
                **line,
                "type": "LIST_ITEM",
                "marker": list_match.group(1),
                "item_text": list_match.group(2).strip()
            }

        # Rule 4: LIST_CONT (not bold, indented, follows list item or previous continuation)
        if not bold and (x0 > self.margin_x0 + 5.0) and self.prev_line_type in ("LIST_ITEM", "LIST_CONT"):
            self.prev_line_type = "LIST_CONT"
            return {**line, "type": "LIST_CONT"}

        # Rule 5: BODY
        self.prev_line_type = "BODY"
        return {**line, "type": "BODY"}
