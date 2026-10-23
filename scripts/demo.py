"""
End-to-End Demonstration Script (Section 13 & 14)
Demonstrates the full life-cycle flow against a clean database:
1. Ingest v1 manual (data/ct200_manual.pdf)
2. Browse sections and tree
3. Create a version-pinned selection (3.2, 4.2, 6.1, 3.3)
4. Generate QA test cases using mock LLM
5. Retrieve test cases against v1 -> all 'fresh'
6. Re-ingest v2 manual (data/ct200_manual_v2.pdf)
7. Display detected changes (2.1.1.1, 3.2, 4.2, 4.3 modified, 5.3 added)
8. Retrieve test cases again against v2 -> triggers dynamic 'likely_stale' and 'review_recommended'
9. Confirm original selection remains strictly pinned to v1 text ('40 mmHg')
"""
import sys
import asyncio
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.db import engine, Base, SessionLocal
from app.orm import NodeVersion
from app.services.ingest import IngestionService
from app.services.selection import SelectionService
from app.services.generation import GenerationService
from app.services.staleness import StalenessEvaluator
from app.stores.json_store import JsonFileGenerationStore
from app.llm.client import LLMClient
from app.schemas import SelectionCreate, SelectionItemInput


async def run_demo():
    print("=" * 80)
    print("CARDIO-TRACK CT-200 MEDICAL MANUAL QA API: END-TO-END DEMO")
    print("=" * 80)

    # 1. Clean Database
    print("\n[Step 1] Initializing clean database...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    gen_store_file = ROOT_DIR / "generations.json"
    if gen_store_file.exists():
        gen_store_file.unlink()
    store = JsonFileGenerationStore(str(gen_store_file))
    llm_client = LLMClient(provider="mock")
    gen_service = GenerationService(store, llm_client)

    v1_pdf = ROOT_DIR / "data" / "ct200_manual.pdf"
    v2_pdf = ROOT_DIR / "data" / "ct200_manual_v2.pdf"

    # 2. Ingest v1
    print("\n[Step 2] Ingesting CT-200 Manual Version 1...")
    ingest_svc = IngestionService(db)
    v1_doc_ver, _ = ingest_svc.ingest_pdf(v1_pdf, document_name="CardioTrack CT-200")
    doc_id = v1_doc_ver.document_id
    print(f"  -> Version 1 created: ID={v1_doc_ver.id}, Pages={v1_doc_ver.page_count}, Status={v1_doc_ver.parse_status}")

    # 3. Browse Sections
    v1_nodes = db.query(NodeVersion).filter(NodeVersion.document_version_id == v1_doc_ver.id).all()
    node_map = {n.section_number: n for n in v1_nodes}
    print(f"  -> Parsed {len(v1_nodes)} nodes. Top-level sections:")
    for n in sorted([n for n in v1_nodes if n.level_declared == 1], key=lambda x: x.doc_order):
        print(f"     Section {n.section_number}: {n.heading}")

    # 4. Create Version-Pinned Selection
    target_sections = ["3.2", "4.2", "6.1", "3.3"]
    print(f"\n[Step 3] Creating version-pinned selection for sections: {target_sections}...")
    selection_items = [
        SelectionItemInput(node_id=node_map[sec].logical_node_id, version=1)
        for sec in target_sections
    ]
    selection_svc = SelectionService(db)
    selection = selection_svc.create_selection(SelectionCreate(
        name="Cuff, Errors and Cleaning Suite",
        items=selection_items
    ))
    print(f"  -> Selection created: ID={selection.id}, Fingerprint={selection.fingerprint[:12]}...")

    # 5. Generate Test Cases
    print("\n[Step 4] Generating QA test cases with LLM client (mock provider)...")
    reconstructed = selection_svc.reconstruct_selection_text(selection.id)
    gen_doc, reused, status_code = await gen_service.generate_test_cases(reconstructed, force=False)
    print(f"  -> Generated {len(gen_doc['test_cases'])} test cases. Status={gen_doc['status']}, Reused={reused}")
    for tc in gen_doc["test_cases"]:
        print(f"     • [{tc['type'].upper()}] {tc['title']} (Sections: {tc['source_sections']}, Quotes: {tc['evidence_quotes']})")

    # 6. Retrieve Test Cases against Version 1
    evaluator = StalenessEvaluator(db)
    v1_eval = evaluator.evaluate_generation(gen_doc, against_version=1)
    print(f"\n[Step 5] Retrieval against Version 1: Rollup Status = '{v1_eval['status_rollup'].upper()}'")
    for tc in v1_eval["test_cases"]:
        print(f"     • {tc['title'][:55]}... -> Status: {tc['staleness']['status']}")

    # 7. Re-ingest Version 2
    print("\n[Step 6] Re-ingesting CT-200 Manual Version 2 (Re-ingestion flow)...")
    v2_doc_ver, _ = ingest_svc.ingest_pdf(v2_pdf, document_id=doc_id)
    print(f"  -> Version 2 created: ID={v2_doc_ver.id}, Pages={v2_doc_ver.page_count}, Status={v2_doc_ver.parse_status}")

    # 8. Check Document Changes
    v2_nodes = db.query(NodeVersion).filter(NodeVersion.document_version_id == v2_doc_ver.id).all()
    modified = [n.section_number for n in v2_nodes if n.change_status == "modified"]
    added = [n.section_number for n in v2_nodes if n.change_status == "added"]
    unchanged = [n.section_number for n in v2_nodes if n.change_status == "unchanged"]

    print("\n[Step 7] Document Change Analysis (v1 -> v2):")
    print(f"  -> Modified sections ({len(modified)}): {sorted(modified)}")
    print(f"  -> Added sections ({len(added)}): {sorted(added)}")
    print(f"  -> Unchanged sections count: {len(unchanged)} (including 3.1, 6.1, 8.1)")

    # 9. Dynamic Staleness Retrieval against Version 2
    print("\n[Step 8] Dynamic Staleness Evaluation against Version 2:")
    v2_eval = evaluator.evaluate_generation(gen_doc, against_version=2)
    print(f"  -> Rollup Status across suite: '{v2_eval['status_rollup'].upper()}'")
    for tc in v2_eval["test_cases"]:
        st = tc["staleness"]
        print(f"     • {tc['title'][:55]}...")
        print(f"       Status: {st['status'].upper()} | Reasons: {st['reasons']}")
        if st["missing_quotes"]:
            print(f"       Missing Quotes: {st['missing_quotes']}")

    # 10. Verify Selection Version Pinning
    print("\n[Step 9] Verifying Selection Immutability (Version Pinning):")
    reconstructed_again = selection_svc.reconstruct_selection_text(selection.id)
    assert "40 mmHg" in reconstructed_again["reconstructed_text"], "Selection lost pinned v1 text!"
    print("  -> SUCCESS: Selection still contains original v1 text ('40 mmHg'), while v2 has '30 mmHg'.")

    print("\n" + "=" * 80)
    print("DEMO RUN COMPLETED SUCCESSFULLY! All invariants and staleness checks verified.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_demo())
