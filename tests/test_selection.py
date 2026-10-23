"""
Selection API and Version Pinning Unit Tests (Test 15 from Section 12)
Validates that selections are strictly pinned to their original node_version snapshots:
A selection created on v1 preserves the v1 text ('40 mmHg') even after v2 is ingested ('30 mmHg').
"""
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.orm import NodeVersion
from app.services.ingest import IngestionService
from app.services.selection import SelectionService
from app.schemas import SelectionCreate, SelectionItemInput

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


def test_selection_version_pinning(test_db):
    ingest_svc = IngestionService(test_db)
    selection_svc = SelectionService(test_db)

    # Ingest v1
    v1_doc_ver, _ = ingest_svc.ingest_pdf(V1_PATH, document_name="CardioTrack CT-200")
    doc_id = v1_doc_ver.document_id

    # Find logical ID of section 3.2 in v1
    n3_2_v1 = test_db.query(NodeVersion).filter(
        NodeVersion.document_version_id == v1_doc_ver.id,
        NodeVersion.section_number == "3.2"
    ).first()
    assert n3_2_v1 is not None
    assert "40 mmHg" in n3_2_v1.body_text

    # Create selection on v1
    selection_input = SelectionCreate(
        name="Cuff inflation test set",
        items=[SelectionItemInput(node_id=n3_2_v1.logical_node_id, version=1)]
    )
    selection = selection_svc.create_selection(selection_input)
    assert selection.id is not None

    # Now ingest v2
    v2_doc_ver, _ = ingest_svc.ingest_pdf(V2_PATH, document_id=doc_id)

    # Verify latest node version has modified text ('30 mmHg')
    n3_2_v2 = test_db.query(NodeVersion).filter(
        NodeVersion.document_version_id == v2_doc_ver.id,
        NodeVersion.section_number == "3.2"
    ).first()
    assert n3_2_v2 is not None
    assert "30 mmHg" in n3_2_v2.body_text

    # CRITICAL TEST: Reconstructing selection text still yields pinned v1 text ('40 mmHg')!
    reconstructed = selection_svc.reconstruct_selection_text(selection.id)
    assert "40 mmHg" in reconstructed["reconstructed_text"]
    assert "30 mmHg" not in reconstructed["reconstructed_text"]
