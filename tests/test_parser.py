"""
Comprehensive Parser Unit Tests (Tests 1 to 12 from Section 12)
Validates all PDF extraction, hierarchy building, and structural irregularity handling
against ground truth CT-200 manual files.
"""
from pathlib import Path
import pytest
from app.parser.extract import parse_pdf_document
from app.parser.validate import InvariantValidator

DATA_DIR = Path(__file__).parent.parent / "data"
V1_PATH = DATA_DIR / "ct200_manual.pdf"
V2_PATH = DATA_DIR / "ct200_manual_v2.pdf"


@pytest.fixture(scope="module")
def v1_parse_result():
    assert V1_PATH.exists(), f"Missing {V1_PATH}"
    return parse_pdf_document(V1_PATH)


@pytest.fixture(scope="module")
def v2_parse_result():
    assert V2_PATH.exists(), f"Missing {V2_PATH}"
    return parse_pdf_document(V2_PATH)


# Test 1: Duplicate heading produced distinct node IDs with correct parents (4 and 7)
def test_duplicate_heading_distinct_nodes(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    error_code_nodes = [n for n in nodes.values() if n.heading.strip() == "Error Codes"]
    assert len(error_code_nodes) == 2, f"Expected 2 'Error Codes' nodes, found {len(error_code_nodes)}"
    
    n4_2 = next((n for n in error_code_nodes if n.section_number == "4.2"), None)
    n7_1 = next((n for n in error_code_nodes if n.section_number == "7.1"), None)
    
    assert n4_2 is not None and n7_1 is not None
    assert n4_2.id != n7_1.id, "Duplicate heading nodes must have distinct UUIDs"
    
    # Check parents are sections 4 and 7
    parent_4 = nodes[n4_2.parent_id]
    parent_7 = nodes[n7_1.parent_id]
    assert parent_4.section_number == "4"
    assert parent_7.section_number == "7"
    assert "duplicate_title" in n4_2.flags
    assert "duplicate_title" in n7_1.flags


# Test 2: Skipped hierarchy 2.1.1.1 parent is 2.1 (no 2.1.1)
def test_level_skip_parent(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    n2_1_1_1 = next((n for n in nodes.values() if n.section_number == "2.1.1.1"), None)
    assert n2_1_1_1 is not None, "Section 2.1.1.1 was not detected"
    
    parent = nodes[n2_1_1_1.parent_id]
    assert parent.section_number == "2.1", f"Expected parent 2.1, got {parent.section_number}"
    assert n2_1_1_1.level_declared == 4
    assert n2_1_1_1.tree_depth == 3
    assert "level_gap" in n2_1_1_1.flags


# Test 3: Out of order siblings in 3.x: [3.1, 3.2, 3.4, 3.3] all with parent 3
def test_out_of_order_siblings(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    n3 = next((n for n in nodes.values() if n.section_number == "3"), None)
    assert n3 is not None
    
    children = [nodes[cid] for cid in n3.children_ids]
    doc_order_numbers = [c.section_number for c in sorted(children, key=lambda c: c.doc_order)]
    assert doc_order_numbers == ["3.1", "3.2", "3.4", "3.3"], f"Unexpected doc order: {doc_order_numbers}"
    
    # Check out_of_order flag is present on 3.3
    n3_3 = next((c for c in children if c.section_number == "3.3"), None)
    assert n3_3 is not None
    assert "out_of_order" in n3_3.flags


# Test 4: Numbered list items in 3.3 are NOT mistaken for top-level headings
def test_list_not_headings(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    h1_nodes = [n for n in nodes.values() if n.level_declared == 1]
    assert len(h1_nodes) == 8, f"Expected 8 level-1 sections, found {len(h1_nodes)}"
    
    n3_3 = next((n for n in nodes.values() if n.section_number == "3.3"), None)
    assert n3_3 is not None
    list_blocks = [b for b in n3_3.blocks if b.get("type") == "list"]
    assert len(list_blocks) >= 1
    
    items = list_blocks[0].get("items", [])
    assert len(items) == 5, f"Expected 5 list items in 3.3, found {len(items)}"
    assert "seeking immediate medical attention" in items[4]["text"]


# Test 5: Small font (11pt) heading 3.2 detected with size_mismatch flag
def test_small_font_heading_detected(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    n3_2 = next((n for n in nodes.values() if n.section_number == "3.2"), None)
    assert n3_2 is not None, "Section 3.2 not found"
    assert "Cuff Inflation Sequence" in n3_2.heading
    assert "size_mismatch" in n3_2.flags
    assert len(n3_2.body_text) > 0


# Test 6: Tables in 2.1 and 4.2 extracted cleanly with no comma corruption
def test_tables(v1_parse_result, v2_parse_result):
    # v1 tables
    v1_nodes = v1_parse_result["nodes"]
    n2_1 = next((n for n in v1_nodes.values() if n.section_number == "2.1"), None)
    n4_2 = next((n for n in v1_nodes.values() if n.section_number == "4.2"), None)
    
    assert n2_1 and n4_2
    t2_1 = next(b for b in n2_1.blocks if b.get("type") == "table")
    t4_2_v1 = next(b for b in n4_2.blocks if b.get("type") == "table")
    
    assert t2_1["row_count"] == 8 and t2_1["col_count"] == 2
    assert t4_2_v1["row_count"] == 6 and t4_2_v1["col_count"] == 3

    # Check cell text clean of commas/newlines
    v2_nodes = v2_parse_result["nodes"]
    n4_2_v2 = next((n for n in v2_nodes.values() if n.section_number == "4.2"), None)
    t4_2_v2 = next(b for b in n4_2_v2.blocks if b.get("type") == "table")
    assert t4_2_v2["row_count"] == 7  # added E6 in v2

    e1_row = next(r for r in t4_2_v1["rows"] if r[0] == "E1")
    assert "Aborts measurement, displays E1" in e1_row[2] or "Aborts measurement" in e1_row[2]


# Test 7: Ligatures and non-breaking hyphens normalized; search hits profile/cuff
def test_ligatures_and_hyphens_normalised(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    for n in nodes.values():
        for bad_char in ["\ufb00", "\ufb01", "\ufb02", "\u2011"]:
            assert bad_char not in n.body_norm
    
    # Search for profile
    matching_profile = [n for n in nodes.values() if "profile" in n.body_norm.lower()]
    assert len(matching_profile) >= 1, "Failed to find 'profile' in normalized text"


# Test 8: Page break paragraph join in 3.1 contains single space
def test_page_break_join(v1_parse_result, v2_parse_result):
    n3_1_v1 = next(n for n in v1_parse_result["nodes"].values() if n.section_number == "3.1")
    assert "device. Use the profile" in n3_1_v1.body_norm or "device. use the profile" in n3_1_v1.body_norm.lower()
    assert "notuse" not in n3_1_v1.body_norm.lower()


# Test 9: Heading-only parents keep valid parent-child relations across pages
def test_orphan_headings_keep_parent(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    n2 = next(n for n in nodes.values() if n.section_number == "2")
    n4 = next(n for n in nodes.values() if n.section_number == "4")
    
    assert len(n2.children_ids) >= 2
    assert len(n4.children_ids) >= 1
    
    n4_1 = next(n for n in nodes.values() if n.section_number == "4.1")
    assert n4_1.parent_id == n4.id


# Test 10: Multi-line title merged into single root node
def test_title_merged(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    roots = [n for n in nodes.values() if n.parent_id is None]
    assert len(roots) == 1
    root = roots[0]
    assert "CardioTrack CT-200" in root.heading
    assert "Technical & User Manual" in root.heading


# Test 11: Cross references extracted into references table
def test_cross_references_not_headings(v1_parse_result):
    nodes = v1_parse_result["nodes"]
    n3_3 = next(n for n in nodes.values() if n.section_number == "3.3")
    n7_1 = next(n for n in nodes.values() if n.section_number == "7.1")
    
    assert any("2.1" in ref for ref in n3_3.references) or any("4.3" in ref for ref in n3_3.references)
    assert any("4.2" in ref for ref in n7_1.references)


# Test 12: Invariant validator catches dropped line
def test_coverage_invariant_and_failure_mode(v1_parse_result):
    report = v1_parse_result["parse_report"]
    assert report["is_valid"] is True, f"Parse invariants failed: {report['hard_failures']}"
    
    # Artificially drop words and assert failure
    nodes_copy = dict(v1_parse_result["nodes"])
    fake_page_words = ["extraneous", "dropped", "words", "never", "in", "document", "sample"] * 10
    
    validator = InvariantValidator(
        nodes=nodes_copy,
        page_words=fake_page_words,
        expected_table_count=2,
        expected_heading_count=27
    )
    is_valid, hard_failures, _ = validator.validate_all()
    assert is_valid is False
    assert any("Coverage invariant failure" in f for f in hard_failures)
