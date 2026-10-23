"""
LLM Generation Service (Sections 9.1 - 9.6)
Implements:
- Deduplication policy (idempotent by fingerprint + model, explicit force regeneration)
- Multi-step repair loop for malformed JSON and schema errors
- Grounding validator (drops ungrounded or hallucinated evidence quotes)
- Full audit persistence for all attempts
"""
import re
import json
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.llm.client import LLMClient
from app.llm.schemas import LLMOutput, TestCase
from app.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, REPAIR_PROMPT_TEMPLATE
from app.stores.base import GenerationStore
from app.parser.normalize import normalize_text

_generation_locks: Dict[str, asyncio.Lock] = {}


def extract_json_payload(raw_text: str) -> str:
    """Strips markdown fences or surrounding prose, extracting the first balanced JSON object."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]
    return text


def clean_for_grounding(text: str) -> str:
    """Normalizes text for grounding substring matching, collapsing whitespace and pipe chars."""
    norm = normalize_text(text).replace("|", " ")
    return re.sub(r"\s+", " ", norm).strip().lower()


class GenerationService:
    def __init__(self, store: GenerationStore, client: Optional[LLMClient] = None):
        self.store = store
        self.client = client or LLMClient()

    async def generate_test_cases(
        self,
        selection_data: Dict[str, Any],
        force: bool = False
    ) -> Tuple[Dict[str, Any], bool, int]:
        """
        Generates QA test cases from selection text.
        Returns: (generation_dict, reused: bool, http_status_code)
        """
        selection_id = selection_data["selection_id"]
        fingerprint = selection_data["fingerprint"]
        reconstructed_text = selection_data["reconstructed_text"]
        source_snapshot = selection_data["source_snapshot"]

        model_name = settings.LLM_MODEL
        lock_key = f"{fingerprint}:{PROMPT_VERSION}:{model_name}"

        if lock_key not in _generation_locks:
            _generation_locks[lock_key] = asyncio.Lock()

        async with _generation_locks[lock_key]:
            # Deduplication Check (Section 9.6)
            if not force:
                existing = self.store.find_active_by_key(fingerprint, PROMPT_VERSION, model_name)
                if existing:
                    return existing, True, 200

            # Find old generation if force=True
            previous_gen = self.store.find_active_by_key(fingerprint, PROMPT_VERSION, model_name) if force else None

            # Prepare Prompt
            user_prompt = USER_PROMPT_TEMPLATE.format(reconstructed_text=reconstructed_text)
            
            gen_id = f"gen_{uuid.uuid4()}"
            attempts_audit: List[Dict[str, Any]] = []
            warnings: List[str] = []
            final_test_cases: List[Dict[str, Any]] = []
            status = "failed"

            # Generation & Repair Loop (Max LLM_MAX_REPAIR_ATTEMPTS + 1)
            current_user_prompt = user_prompt
            max_attempts = settings.LLM_MAX_REPAIR_ATTEMPTS + 1

            # Prepare source text corpus for grounding validation
            valid_source_sections = {item["section_number"] for item in source_snapshot}
            grounding_corpus = clean_for_grounding(reconstructed_text)

            for attempt_n in range(1, max_attempts + 1):
                try:
                    raw_output, meta = self.client.chat_json(SYSTEM_PROMPT, current_user_prompt)
                except Exception as req_err:
                    # Provider error
                    error_msg = f"LLM Request failed: {str(req_err)}"
                    attempts_audit.append({"n": attempt_n, "raw": "", "error": error_msg, "latency_ms": 0})
                    if attempt_n == max_attempts:
                        self._save_failed_generation(gen_id, selection_id, fingerprint, model_name, source_snapshot, attempts_audit, warnings)
                        raise HTTPException(status_code=503, detail="Provider transient error after retries.")
                    continue

                extracted_json_str = extract_json_payload(raw_output)

                # Step 1: JSON Parsing
                try:
                    parsed_dict = json.loads(extracted_json_str)
                except json.JSONDecodeError as jde:
                    err_msg = f"JSONDecodeError: {str(jde)}"
                    attempts_audit.append({"n": attempt_n, "raw": raw_output, "error": err_msg, "latency_ms": meta.get("latency_ms", 0)})
                    current_user_prompt = REPAIR_PROMPT_TEMPLATE.format(
                        reconstructed_text=reconstructed_text,
                        previous_raw=raw_output,
                        error_details=err_msg
                    )
                    continue

                # Step 2: Pydantic Schema Validation
                try:
                    validated_output = LLMOutput.model_validate(parsed_dict)
                except ValidationError as ve:
                    err_msg = f"SchemaValidationError: {ve.errors()}"
                    attempts_audit.append({"n": attempt_n, "raw": raw_output, "error": err_msg, "latency_ms": meta.get("latency_ms", 0)})
                    current_user_prompt = REPAIR_PROMPT_TEMPLATE.format(
                        reconstructed_text=reconstructed_text,
                        previous_raw=raw_output,
                        error_details=str(ve.errors())
                    )
                    continue

                # Step 3: Grounding Check on test cases
                valid_cases = []
                for idx, tc in enumerate(validated_output.test_cases):
                    tc_dict = tc.model_dump()
                    tc_dict["id"] = f"tc_{idx + 1}"

                    # Verify section cited
                    cited_valid = any(sec in valid_source_sections for sec in tc.source_sections)
                    if not cited_valid:
                        warnings.append(f"TestCase '{tc.title}' dropped: cites section {tc.source_sections} not in selection.")
                        continue

                    # Verify evidence quotes are verbatim substrings
                    quotes_valid = True
                    for quote in tc.evidence_quotes:
                        norm_q = clean_for_grounding(quote)
                        if norm_q not in grounding_corpus:
                            quotes_valid = False
                            warnings.append(f"TestCase '{tc.title}' dropped: evidence quote '{quote}' not found in source text.")
                            break

                    if quotes_valid:
                        valid_cases.append(tc_dict)

                # Check minimum valid test cases (Requirement: 3 to 5)
                if len(valid_cases) < 3:
                    err_msg = f"Insufficient valid cases after grounding check ({len(valid_cases)} valid; minimum 3 required)."
                    attempts_audit.append({"n": attempt_n, "raw": raw_output, "error": err_msg, "latency_ms": meta.get("latency_ms", 0)})
                    current_user_prompt = REPAIR_PROMPT_TEMPLATE.format(
                        reconstructed_text=reconstructed_text,
                        previous_raw=raw_output,
                        error_details=err_msg
                    )
                    continue

                # Truncate to 5 if more than 5
                if len(valid_cases) > 5:
                    valid_cases = valid_cases[:5]
                    warnings.append("truncated_to_5")

                # Successful generation!
                attempts_audit.append({"n": attempt_n, "raw": raw_output, "error": None, "latency_ms": meta.get("latency_ms", 0)})
                final_test_cases = valid_cases
                status = "completed_with_warnings" if warnings else "completed"
                break

            # If all attempts failed
            if status == "failed":
                self._save_failed_generation(
                    gen_id, selection_id, fingerprint, model_name, source_snapshot, attempts_audit, warnings
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"All {max_attempts} LLM generation attempts produced invalid or ungrounded outputs. Raw attempts logged."
                )

            # Store completed generation
            generation_doc = {
                "_id": gen_id,
                "selection_id": selection_id,
                "selection_fingerprint": fingerprint,
                "prompt_version": PROMPT_VERSION,
                "provider": self.client.provider,
                "model": model_name,
                "status": status,
                "supersedes": previous_gen["_id"] if previous_gen else None,
                "superseded_by": None,
                "created_at": datetime.utcnow().isoformat(),
                "source_snapshot": source_snapshot,
                "test_cases": final_test_cases,
                "attempts": attempts_audit,
                "warnings": warnings
            }

            if previous_gen:
                previous_gen["superseded_by"] = gen_id
                self.store.save(previous_gen)

            self.store.save(generation_doc)
            return generation_doc, False, 201

    def _save_failed_generation(self, gen_id, selection_id, fingerprint, model_name, source_snapshot, attempts, warnings):
        doc = {
            "_id": gen_id,
            "selection_id": selection_id,
            "selection_fingerprint": fingerprint,
            "prompt_version": PROMPT_VERSION,
            "provider": self.client.provider,
            "model": model_name,
            "status": "failed",
            "supersedes": None,
            "superseded_by": None,
            "created_at": datetime.utcnow().isoformat(),
            "source_snapshot": source_snapshot,
            "test_cases": [],
            "attempts": attempts,
            "warnings": warnings
        }
        self.store.save(doc)
