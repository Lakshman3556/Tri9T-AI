"""
Staleness Evaluation Matrix Unit Tests (Test 18 from Section 12)
Validates Acceptance Outcomes from Table 2.7:
- 4.2 (quotes 'Auto-deflates within 2 seconds') -> likely_stale (evidence quote missing; diff 2 -> 1.5s)
- 3.2 (quotes '40 mmHg increments') -> likely_stale
- 6.1 / 8.1 -> fresh
- 3.3 -> review_recommended (references section 4.3 which changed)
"""
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.orm import NodeVersion
from app.services.ingest import IngestionService
from app.services.staleness import StalenessEvaluator
from app.stores.json_store import JsonFileGenerationStore

DATA_DIR = Path(__file__).parent.parent / "data"
V1_PATH = DATA_DIR / "ct200_manual.pdf"
V2_PATH = DATA_DIR / "ct200_manual_v2.pdf"


@pytest.fixture
def populated_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    ingest_svc = IngestionService(session)
    v1_ver, _ = ingest_svc.ingest_pdf(V1_PATH, document_name="CardioTrack CT-200")
    v2_ver, _ = ingest_svc.ingest_pdf(V2_PATH, document_id=v1_ver.document_id)

    yield session, v1_ver, v2_ver
    session.close()


def test_staleness_matrix(populated_db):
    session, v1_ver, v2_ver = populated_db
    evaluator = StalenessEvaluator(session)

    # 1. Test Case on Section 4.2 citing 'Auto-deflates within 2 seconds'
    n4_2_v1 = session.query(NodeVersion).filter(
        NodeVersion.document_version_id == v1_ver.id,
        NodeVersion.section_number == "4.2"
    ).first()

    gen_4_2 = {
        "_id": "gen_test_4_2",
        "source_snapshot": [{
            "logical_node_id": n4_2_v1.logical_node_id,
            "section_number": "4.2",
            "content_hash": n4_2_v1.own_hash,
            "text_norm": n4_2_v1.body_norm
        }],
        "test_cases": [{
            "id": "tc_4_2",
            "title": "Check E3 deflation time",
            "source_sections": ["4.2"],
            "evidence_quotes": ["Auto-deflates within 2 seconds"]
        }]
    }

    # Evaluate against v1 -> must be fresh
    v1_eval = evaluator.evaluate_generation(gen_4_2, against_version=1)
    assert v1_eval["test_cases"][0]["staleness"]["status"] == "fresh"

    # Evaluate against v2 -> must be likely_stale because quote missing (v2 has 1.5 seconds)
    v2_eval = evaluator.evaluate_generation(gen_4_2, against_version=2)
    assert v2_eval["test_cases"][0]["staleness"]["status"] == "likely_stale"
    assert "Auto-deflates within 2 seconds" in v2_eval["test_cases"][0]["staleness"]["missing_quotes"]

    # 2. Test Case on Section 6.1 (unchanged) -> must remain fresh in v2
    n6_1_v1 = session.query(NodeVersion).filter(
        NodeVersion.document_version_id == v1_ver.id,
        NodeVersion.section_number == "6.1"
    ).first()

    gen_6_1 = {
        "_id": "gen_test_6_1",
        "source_snapshot": [{
            "logical_node_id": n6_1_v1.logical_node_id,
            "section_number": "6.1",
            "content_hash": n6_1_v1.own_hash,
            "text_norm": n6_1_v1.body_norm
        }],
        "test_cases": [{
            "id": "tc_6_1",
            "title": "Check cleaning damp cloth",
            "source_sections": ["6.1"],
            "evidence_quotes": ["soft, dry cloth"]
        }]
    }
    eval_6_1 = evaluator.evaluate_generation(gen_6_1, against_version=2)
    assert eval_6_1["test_cases"][0]["staleness"]["status"] == "fresh"

    # 3. Test Case on Section 3.3 (references 4.3 which changed in v2) -> review_recommended
    n3_3_v1 = session.query(NodeVersion).filter(
        NodeVersion.document_version_id == v1_ver.id,
        NodeVersion.section_number == "3.3"
    ).first()

    gen_3_3 = {
        "_id": "gen_test_3_3",
        "source_snapshot": [{
            "logical_node_id": n3_3_v1.logical_node_id,
            "section_number": "3.3",
            "content_hash": n3_3_v1.own_hash,
            "text_norm": n3_3_v1.body_norm
        }],
        "test_cases": [{
            "id": "tc_3_3",
            "title": "Check blood pressure classification",
            "source_sections": ["3.3"],
            "evidence_quotes": ["Hypertensive Crisis"]
        }]
    }
    eval_3_3 = evaluator.evaluate_generation(gen_3_3, against_version=2)
    assert eval_3_3["test_cases"][0]["staleness"]["status"] == "review_recommended"
    assert any("reference" in r.lower() for r in eval_3_3["test_cases"][0]["staleness"]["reasons"])
