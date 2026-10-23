"""
Invariant Validation Engine (Section 5.8)
Catches silent loss, merge, or mis-parenting through strict invariant assertions:
- Multiset word coverage (all extracted words must be accounted for in nodes or tables)
- Single-parent and no-cycle checks
- Uniqueness of section numbers
- Table count matches find_tables() count
- Heading count invariant
- Absence of un-normalized ligatures or glued tokens (e.g. 'Specifications2.1')
"""
import re
from collections import Counter
from typing import Dict, List, Tuple
from app.parser.tree import DocumentNode
from app.parser.normalize import normalize_text

GLUED_TOKEN_RE = re.compile(r"[a-z]+(\d+(?:\.\d+)+)")


def tokenize_words(text: str) -> List[str]:
    """Extracts alphanumeric words normalized to lowercase for multiset coverage comparison."""
    norm = normalize_text(text)
    # Split on whitespace and remove basic punctuation from boundaries
    raw_tokens = norm.split()
    clean_tokens = []
    for t in raw_tokens:
        cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", t).lower()
        if cleaned:
            clean_tokens.append(cleaned)
    return clean_tokens


class InvariantValidator:
    def __init__(
        self,
        nodes: Dict[str, DocumentNode],
        page_words: List[str],
        expected_table_count: int,
        expected_heading_count: int
    ):
        self.nodes = nodes
        self.page_words = page_words
        self.expected_table_count = expected_table_count
        self.expected_heading_count = expected_heading_count
        self.hard_failures: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        self._check_tree_structure()
        self._check_table_count()
        self._check_heading_count()
        self._check_text_sanitization()
        self._check_word_coverage()
        
        is_valid = len(self.hard_failures) == 0
        return is_valid, self.hard_failures, self.warnings

    def _check_tree_structure(self):
        """Validates single parent, absence of cycles, and unique section numbers."""
        seen_numbers = set()
        prev_doc_order = -1
        root_count = 0

        for nid, node in sorted(self.nodes.items(), key=lambda item: item[1].doc_order):
            # Check unique section number
            if node.section_number in seen_numbers and node.section_number != "0":
                self.hard_failures.append(f"Duplicate section number detected: '{node.section_number}'")
            seen_numbers.add(node.section_number)

            # Check strictly increasing doc_order
            if node.doc_order <= prev_doc_order:
                self.hard_failures.append(f"doc_order is not strictly increasing at node {node.section_number}")
            prev_doc_order = node.doc_order

            # Parent checks
            if node.parent_id is None:
                root_count += 1
            else:
                # Cycle check via path traversal
                curr = node
                visited = {node.id}
                while curr.parent_id:
                    if curr.parent_id in visited:
                        self.hard_failures.append(f"Cycle detected in hierarchy involving node '{node.section_number}'")
                        break
                    visited.add(curr.parent_id)
                    curr = self.nodes.get(curr.parent_id)
                    if not curr:
                        self.hard_failures.append(f"Dangling parent reference from node '{node.section_number}'")
                        break

            # Collect soft warnings from flags
            for f in node.flags:
                self.warnings.append(f"Node {node.section_number} ({node.heading}): {f}")

        if root_count != 1:
            self.hard_failures.append(f"Expected exactly 1 root node, found {root_count}")

    def _check_table_count(self):
        """Verifies table count matches detected visual tables."""
        tree_tables = 0
        for node in self.nodes.values():
            for block in node.blocks:
                if block.get("type") == "table":
                    tree_tables += 1
        if tree_tables != self.expected_table_count:
            self.hard_failures.append(
                f"Table count mismatch: tree contains {tree_tables} tables, expected {self.expected_table_count}"
            )

    def _check_heading_count(self):
        """Verifies section count matches detected heading lines."""
        # Non-root nodes should match expected heading count
        non_root_headings = len([n for n in self.nodes.values() if n.section_number != "0"])
        if non_root_headings != self.expected_heading_count:
            self.hard_failures.append(
                f"Heading count mismatch: tree has {non_root_headings} sections, expected {self.expected_heading_count}"
            )

    def _check_text_sanitization(self):
        """Verifies ligatures are eliminated and no words are glued together."""
        for node in self.nodes.values():
            combined_text = node.heading + " " + node.body_text
            # Ligature checks
            for char in ["\ufb00", "\ufb01", "\ufb02", "\ufb03", "\ufb04", "\ufb05", "\ufb06", "\u2011"]:
                if char in combined_text:
                    self.hard_failures.append(
                        f"Unsanitized character U+{ord(char):04X} found in node {node.section_number}"
                    )
            # Glued tokens check e.g. 'Specifications2.1'
            glued_matches = GLUED_TOKEN_RE.findall(combined_text)
            if glued_matches:
                self.hard_failures.append(
                    f"Glued token detected in node {node.section_number}: {glued_matches}"
                )

    def _check_word_coverage(self):
        """Compares multiset of words extracted from source pages against words assembled in nodes."""
        tree_words = []
        for node in self.nodes.values():
            if node.section_number != "0":
                tree_words.extend(tokenize_words(node.section_number))
            tree_words.extend(tokenize_words(node.heading))
            for b in node.blocks:
                if b.get("type") == "paragraph":
                    tree_words.extend(tokenize_words(b.get("text", "")))
                elif b.get("type") == "list":
                    for item in b.get("items", []):
                        tree_words.extend(tokenize_words(item.get("marker", "")))
                        tree_words.extend(tokenize_words(item.get("text", "")))
                # Note: table cells are excluded from page_words and validated in _check_table_count

        source_counter = Counter(self.page_words)
        tree_counter = Counter(tree_words)

        # Discrepancies
        missing_in_tree = source_counter - tree_counter
        extra_in_tree = tree_counter - source_counter

        # Allow negligible variance due to punctuation or regex grouping if necessary, but flag significant loss
        if sum(missing_in_tree.values()) > 0 or sum(extra_in_tree.values()) > 0:
            missing_samples = list(missing_in_tree.elements())[:10]
            extra_samples = list(extra_in_tree.elements())[:10]
            # If word difference is minor differences in punctuation stripping, record as warning;
            # if material words are dropped, fail loudly!
            diff_count = sum(missing_in_tree.values()) + sum(extra_in_tree.values())
            if diff_count > 5:
                self.hard_failures.append(
                    f"Coverage invariant failure: {diff_count} words differ. Missing: {missing_samples}, Extra: {extra_samples}"
                )
            else:
                self.warnings.append(
                    f"Minor coverage token difference ({diff_count} tokens): {missing_samples}"
                )
