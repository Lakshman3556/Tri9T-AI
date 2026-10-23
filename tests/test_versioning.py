"""
Versioning and Golden Diff Unit Tests (Tests 13, 14, 19 from Section 12)
Validates:
- Golden v1 to v2 diff: Modified = {2.1.1.1, 3.2, 4.2, 4.3}, Added = {5.3}, Unchanged = {3.1, 6.1, 8.1, ...}
- Immutability of v1 rows after v2 ingestion
- Idempotency of re-ingesting the exact same PDF
- Documented matcher failure mode (heavily rewritten section is not forced-matched)
"""
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.orm import Document, DocumentVersion, NodeVersion
from app.services.ingest import IngestionService
from app.services.matching import VersionMatcher
from app.parser.tree import DocumentNode

DATA_DIR = Path(__file__).parent.parent / "data"
V1_PATH = DATA_DIR / "ct200_manual.pdf"
V2_PATH = DATA_DIR / "ct200_manual_v2.pdf"


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_v2_golden_diff(test_db):
    service = IngestionService(test_db)
    # Ingest v1
    v1_doc_ver, _ = service.ingest_pdf(V1_PATH, document_name="CardioTrack CT-200")
    doc_id = v1_doc_ver.document_id

    # Ingest v2
    v2_doc_ver, _ = service.ingest_pdf(V2_PATH, document_id=doc_id)

    # Fetch v2 node versions
    v2_nodes = test_db.query(NodeVersion).filter(
        NodeVersion.document_version_id == v2_doc_ver.id
    ).all()

    modified_sections = {n.section_number for n in v2_nodes if n.change_status == "modified"}
    added_sections = {n.section_number for n in v2_nodes if n.change_status == "added"}
    unchanged_sections = {n.section_number for n in v2_nodes if n.change_status == "unchanged"}

    # Golden assertion (Section 2.5 of brief)
    assert modified_sections == {"2.1.1.1", "3.2", "4.2", "4.3"}, f"Unexpected modified: {modified_sections}"
    assert added_sections == {"5.3"}, f"Unexpected added: {added_sections}"
    
    # Crucial traps must be UNCHANGED: 3.1, 6.1, 8.1
    for trap_section in ["3.1", "6.1", "8.1"]:
        assert trap_section in unchanged_sections, f"Section {trap_section} was falsely flagged as modified!"


def test_v1_preserved_after_v2(test_db):
    service = IngestionService(test_db)
    v1_doc_ver, _ = service.ingest_pdf(V1_PATH, document_name="CardioTrack CT-200")
    doc_id = v1_doc_ver.document_id

    v1_nodes_before = {
        n.section_number: (n.logical_node_id, n.own_hash, n.body_text)
        for n in test_db.query(NodeVersion).filter(NodeVersion.document_version_id == v1_doc_ver.id).all()
    }

    # Ingest v2
    v2_doc_ver, _ = service.ingest_pdf(V2_PATH, document_id=doc_id)

    # Verify v1 rows are strictly immutable
    v1_nodes_after = {
        n.section_number: (n.logical_node_id, n.own_hash, n.body_text)
        for n in test_db.query(NodeVersion).filter(NodeVersion.document_version_id == v1_doc_ver.id).all()
    }
    assert v1_nodes_before == v1_nodes_after, "v1 node records were mutated during v2 ingestion!"

    # Verify logical IDs preserved for unchanged nodes
    v2_nodes = {
        n.section_number: n.logical_node_id
        for n in test_db.query(NodeVersion).filter(NodeVersion.document_version_id == v2_doc_ver.id).all()
    }
    for sec_num in ["1.1", "2.1", "3.1", "6.1", "8.1"]:
        assert v1_nodes_before[sec_num][0] == v2_nodes[sec_num], f"Logical ID drifted for unchanged section {sec_num}"

    # Verify idempotency: re-ingesting v2 returns same version without duplicating rows
    reingest_ver, already_ingested = service.ingest_pdf(V2_PATH, document_id=doc_id)
    assert already_ingested is True
    assert reingest_ver.id == v2_doc_ver.id


def test_matching_failure_mode_documented():
    """
    Test 19: Synthetic edge case.
    A section retitled and completely rewritten in body text drops below fuzzy thresholds
    and is treated as removed + added, rather than creating a silent false match.
    """
    old_node = DocumentNode(
        node_id="old_1",
        section_number="9.1",
        heading="Old Calibration Procedure",
        level_declared=2,
        tree_depth=2,
        parent_id="root_id"
    )
    old_node.body_norm = "calibrate the sensor every thirty days using standard weights."
    old_node.heading_norm = "old calibration procedure"
    old_node.own_hash = "hash_old_9_1"

    new_node = DocumentNode(
        node_id="new_1",
        section_number="9.1",
        heading="Wireless Cloud Sync",
        level_declared=2,
        tree_depth=2,
        parent_id="root_id"
    )
    new_node.body_norm = "connect your mobile application via low energy bluetooth protocol."
    new_node.heading_norm = "wireless cloud sync"
    new_node.own_hash = "hash_new_9_1"

    matcher = VersionMatcher(v_old_nodes={"old_1": old_node}, v_new_nodes={"new_1": new_node})
    results = matcher.match()

    # Must be added, not falsely matched to the old calibration procedure!
    assert results["new_1"]["change_status"] == "added"
    assert results["new_1"]["is_new_logical"] is True
