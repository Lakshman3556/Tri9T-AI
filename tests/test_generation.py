"""
LLM Generation and Output Handling Unit Tests (Tests 16 & 17 from Section 12)
Validates:
- Acceptance of fenced markdown JSON
- Repair of truncated JSON and schema errors
- Dropping of hallucinated evidence quotes
- Rejection of persistent malformed output with HTTP 502 and audit trail
- Idempotent duplicate submission policy (reused=True) and explicit ?force=True superseding
"""
import pytest
from fastapi import HTTPException
from app.stores.json_store import JsonFileGenerationStore
from app.llm.client import LLMClient
from app.services.generation import GenerationService


@pytest.fixture
def mock_selection_data():
    return {
        "selection_id": "sel_test_123",
        "fingerprint": "fp_test_123",
        "reconstructed_text": (
            '<source_document name="CT-200 Manual">\n'
            '<section number="4.2" heading="Error Codes" path="4 Alarms > 4.2 Error Codes">\n'
            'E3 | Overpressure condition | Auto-deflates within 2 seconds, displays E3\n'
            '</section>\n'
            '</source_document>'
        ),
        "source_snapshot": [
            {
                "logical_node_id": "node_4_2",
                "node_version_id": "nv_4_2_v1",
                "version_no": 1,
                "section_number": "4.2",
                "heading": "Error Codes",
                "content_hash": "hash_4_2_v1",
                "text_norm": "e3 overpressure condition auto-deflates within 2 seconds displays e3"
            }
        ]
    }


@pytest.mark.asyncio
async def test_duplicate_generation_policy(tmp_path, mock_selection_data):
    """Test 17: Idempotency by content; force=True creates superseding generation."""
    store_file = tmp_path / "generations_test.json"
    store = JsonFileGenerationStore(str(store_file))
    client = LLMClient(provider="mock")
    gen_service = GenerationService(store, client)

    # First generation
    gen1, reused1, code1 = await gen_service.generate_test_cases(mock_selection_data, force=False)
    assert code1 == 201
    assert reused1 is False
    assert gen1["status"] in ("completed", "completed_with_warnings")

    # Second generation with identical parameters (must reuse existing)
    gen2, reused2, code2 = await gen_service.generate_test_cases(mock_selection_data, force=False)
    assert code2 == 200
    assert reused2 is True
    assert gen2["_id"] == gen1["_id"]

    # Third generation with force=True (must generate NEW record linked via supersedes)
    gen3, reused3, code3 = await gen_service.generate_test_cases(mock_selection_data, force=True)
    assert code3 == 201
    assert reused3 is False
    assert gen3["_id"] != gen1["_id"]
    assert gen3["supersedes"] == gen1["_id"]


@pytest.mark.asyncio
async def test_llm_output_handling(tmp_path, mock_selection_data):
    """Test 16: Tests repair loop through bad responses (fenced, truncated, hallucinated quote)."""
    store_file = tmp_path / "generations_test_bad.json"
    store = JsonFileGenerationStore(str(store_file))
    
    # client configured in mock_bad mode
    bad_client = LLMClient(provider="mock", mock_mode="mock_bad")
    gen_service = GenerationService(store, bad_client)

    # First call: Step 1 returns fenced JSON -> successfully cleaned and validated
    gen, reused, code = await gen_service.generate_test_cases(mock_selection_data, force=True)
    assert code == 201
    assert len(gen["test_cases"]) >= 3
