"""
Diffing and Significance Classification Engine (Section 6.3)
Generates word-level diffs, table row-level diffs, and classifies change significance:
- material: numbers, medical units (mmHg, seconds, %, bpm), error identifiers (E1..E6), modal words
- wording: cosmetic/stylistic prose edits without threshold/safety impact
- none: text identical after normalization
"""
import re
import difflib
from typing import Dict, Any, List, Optional

UNITS = {"mmhg", "seconds", "second", "sec", "%", "cm", "bpm", "cycles", "hz", "v", "ma"}
MODALS = {"not", "no", "never", "must", "should", "shall", "only", "within", "exceeds", "below", "above", "at", "least"}
IDENTIFIER_RE = re.compile(r"^[A-Z]\d+$")


def classify_token_significance(old_tokens: List[str], new_tokens: List[str]) -> str:
    """Classifies whether the difference between old and new tokens is 'material' or 'wording'."""
    all_changed_tokens = set(old_tokens + new_tokens)
    
    for token in all_changed_tokens:
        clean = re.sub(r"^[^\w]+|[^\w]+$", "", token).lower()
        # 1. Any digit
        if any(c.isdigit() for c in clean):
            return "material"
        # 2. Medical or physical units
        if clean in UNITS:
            return "material"
        # 3. Identifiers like E3, E5, E6
        if IDENTIFIER_RE.match(token.strip()):
            return "material"
        # 4. Modals and safety boundaries
        if clean in MODALS:
            return "material"

    return "wording"


def compute_word_diff(old_text: str, new_text: str) -> Dict[str, Any]:
    """Computes word-level diff opcodes and significance."""
    if old_text == new_text:
        return {"significance": "none", "opcodes": [], "change_count": 0}

    old_words = old_text.split()
    new_words = new_text.split()

    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    opcodes = []
    old_changed_tokens = []
    new_changed_tokens = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            old_slice = old_words[i1:i2]
            new_slice = new_words[j1:j2]
            old_changed_tokens.extend(old_slice)
            new_changed_tokens.extend(new_slice)
            opcodes.append({
                "op": tag,
                "old": " ".join(old_slice),
                "new": " ".join(new_slice)
            })

    significance = classify_token_significance(old_changed_tokens, new_changed_tokens)

    return {
        "significance": significance,
        "opcodes": opcodes[:20],  # bounded to 20 ops
        "total_operations": len(opcodes),
        "old_words_count": len(old_words),
        "new_words_count": len(new_words)
    }


def compute_table_diff(old_table_block: Dict[str, Any], new_table_block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes row-level table diff keyed by first column (e.g. E1..E6 or parameter name).
    Specifically handles Section 4.2 table where E3 changed and E6 is added.
    """
    old_rows = {row[0]: row for row in old_table_block.get("rows", []) if row}
    new_rows = {row[0]: row for row in new_table_block.get("rows", []) if row}

    rows_changed = []
    rows_added = []
    rows_removed = []

    for key, new_row in new_rows.items():
        if key not in old_rows:
            rows_added.append(key)
        else:
            old_row = old_rows[key]
            if old_row != new_row:
                rows_changed.append({
                    "row_key": key,
                    "old": " | ".join(old_row),
                    "new": " | ".join(new_row)
                })

    for key in old_rows:
        if key not in new_rows:
            rows_removed.append(key)

    significance = "material" if (rows_changed or rows_added or rows_removed) else "none"

    return {
        "significance": significance,
        "rows_changed": rows_changed,
        "rows_added": rows_added,
        "rows_removed": rows_removed
    }
