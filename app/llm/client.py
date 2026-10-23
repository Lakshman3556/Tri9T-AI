"""
LLM Client with Multi-Provider Support and Deterministic Mock Testing (Section 9.7)
Supports:
- OpenAI-compatible chat endpoints (Groq, Gemini, OpenRouter)
- Canned Mock provider for offline execution and deterministic CI
- 'mock_bad' mode for unit-testing the repair loop and failure handling
"""
import re
import json
import time
import httpx
from typing import Tuple, Dict, Any, Optional
from app.config import settings


class LLMClient:
    def __init__(self, provider: Optional[str] = None, mock_mode: Optional[str] = None):
        self.provider = provider or settings.LLM_PROVIDER
        self.mock_mode = mock_mode  # None | "canned" | "mock_bad"
        self.mock_bad_step = 0

    def chat_json(self, system_prompt: str, user_prompt: str) -> Tuple[str, Dict[str, Any]]:
        """
        Sends request to LLM or deterministic mock.
        Returns: (raw_response_text, metadata_dict)
        """
        start_time = time.time()

        # Handle Mock Providers
        if self.provider == "mock" or not settings.LLM_API_KEY:
            if self.mock_mode == "mock_bad":
                raw_text = self._get_mock_bad_response(user_prompt)
            else:
                raw_text = self._generate_canned_valid_response(user_prompt)
            
            latency_ms = int((time.time() - start_time) * 1000)
            return raw_text, {"provider": "mock", "model": "mock-canned", "latency_ms": latency_ms}

        # Real HTTP Request to OpenAI-compatible endpoint
        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        with httpx.Client(timeout=settings.LLM_TIMEOUT_S) as client:
            resp = client.post(
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
            finish_reason = data["choices"][0].get("finish_reason", "stop")
            latency_ms = int((time.time() - start_time) * 1000)

            return raw_text, {
                "provider": self.provider,
                "model": settings.LLM_MODEL,
                "finish_reason": finish_reason,
                "latency_ms": latency_ms
            }

    def _generate_canned_valid_response(self, user_prompt: str) -> str:
        """Extracts facts and numbers directly from user prompt to synthesize valid grounded test cases."""
        cases = []

        # 1. Section 4.2 Error Codes
        if '<section number="4.2"' in user_prompt:
            quote_4_2 = "Auto-deflates within 1.5 seconds" if "Auto-deflates within 1.5 seconds" in user_prompt else "Auto-deflates within 2 seconds"
            exp_time = "1.5 seconds" if "1.5 seconds" in quote_4_2 else "2 seconds"
            cases.append({
                "title": "Verify E3 overpressure auto-deflation duration",
                "type": "safety",
                "priority": "high",
                "preconditions": ["Pneumatic test rig connected to cuff connector port"],
                "steps": [
                    "Pressurize cuff beyond 300 mmHg threshold",
                    f"Measure deflation response time to reach ambient pressure: must be within {exp_time}"
                ],
                "expected_result": f"Cuff auto-deflates within {exp_time} and display shows error code E3.",
                "source_sections": ["4.2"],
                "evidence_quotes": [quote_4_2]
            })
            if "Overpressure condition" in user_prompt:
                cases.append({
                    "title": "Verify E3 fault code display upon overpressure",
                    "type": "functional",
                    "priority": "medium",
                    "preconditions": ["Device idle and ready"],
                    "steps": [
                        "Inject pressure overload condition into sensor",
                        "Observe visual indicators on device screen"
                    ],
                    "expected_result": "Screen displays error code for Overpressure condition.",
                    "source_sections": ["4.2"],
                    "evidence_quotes": ["Overpressure condition"]
                })
                cases.append({
                    "title": "Verify auto-deflate valve venting under overpressure",
                    "type": "boundary",
                    "priority": "medium",
                    "preconditions": ["Test harness initialized"],
                    "steps": [
                        "Trigger sensor alarm state",
                        "Verify cuff pressure vents immediately"
                    ],
                    "expected_result": f"Cuff pressure vents completely within safety threshold: {quote_4_2}.",
                    "source_sections": ["4.2"],
                    "evidence_quotes": [quote_4_2]
                })

        # 2. Section 3.2 Cuff Inflation Sequence
        if '<section number="3.2"' in user_prompt:
            quote_3_2 = "30 mmHg increments" if "30 mmHg increments" in user_prompt else "40 mmHg increments"
            inc_val = "30 mmHg" if "30" in quote_3_2 else "40 mmHg"
            cases.append({
                "title": "Verify sequential cuff inflation pressure steps",
                "type": "boundary",
                "priority": "medium",
                "preconditions": ["Cuff wrapped snugly around rigid test cylinder"],
                "steps": [
                    "Press Start button to initiate measurement sequence",
                    f"Monitor pressure sensor log: inflation must proceed in {inc_val}"
                ],
                "expected_result": f"Cuff inflates smoothly in calibrated {inc_val}.",
                "source_sections": ["3.2"],
                "evidence_quotes": [quote_3_2]
            })

        # 3. Section 6.1 Cleaning Instructions
        if '<section number="6.1"' in user_prompt:
            cases.append({
                "title": "Verify exterior chassis cleaning protocol",
                "type": "functional",
                "priority": "low",
                "preconditions": ["Device powered off and unplugged"],
                "steps": [
                    "Prepare mild detergent solution",
                    "Wipe exterior using soft damp cloth only",
                    "Verify no liquid penetrates battery compartment"
                ],
                "expected_result": "Device surfaces clean with zero moisture intrusion.",
                "source_sections": ["6.1"],
                "evidence_quotes": ["soft damp cloth"]
            })

        # 4. Section 3.3 Result Display and Classification
        if '<section number="3.3"' in user_prompt:
            cases.append({
                "title": "Verify critical blood pressure category display",
                "type": "safety",
                "priority": "high",
                "preconditions": ["Simulate systolic >= 180 or diastolic >= 120"],
                "steps": [
                    "Submit measurement signal above 180/120 mmHg",
                    "Verify LCD classification indicator and warning icon"
                ],
                "expected_result": "Screen alerts operator with Hypertensive Crisis category.",
                "source_sections": ["3.3"],
                "evidence_quotes": ["Hypertensive Crisis"]
            })

        # Fallback if fewer than 3 cases
        sec_matches = re.findall(r'<section number="([^"]+)"', user_prompt)
        first_sec = sec_matches[0] if sec_matches else "1.1"
        while len(cases) < 3:
            cases.append({
                "title": f"Verify general operational compliance for section {first_sec}",
                "type": "regression",
                "priority": "medium",
                "preconditions": ["Standard operating temperature environment"],
                "steps": [
                    f"Perform functional check according to section {first_sec}",
                    "Record device telemetry and verify expected status"
                ],
                "expected_result": "Device operates consistently without error indicators.",
                "source_sections": [first_sec],
                "evidence_quotes": ["Technical & User Manual" if "Technical & User Manual" in user_prompt else "Device Overview"]
            })

        return json.dumps({"test_cases": cases[:5]})

    def _get_mock_bad_response(self, user_prompt: str) -> str:
        """Iterates through bad responses to test Table 9.5 repair loop."""
        self.mock_bad_step += 1
        
        # Step 1: Fenced markdown
        if self.mock_bad_step == 1:
            valid_json = self._generate_canned_valid_response(user_prompt)
            return f"```json\n{valid_json}\n```"

        # Step 2: Truncated JSON
        if self.mock_bad_step == 2:
            return '{"test_cases": [{"title": "Truncated Test", "type": "safety"'

        # Step 3: Schema violation (missing required fields)
        if self.mock_bad_step == 3:
            return json.dumps({"test_cases": [{"title": "Invalid test without steps"}]})

        # Step 4: Hallucinated evidence quote (grounding check drops this)
        if self.mock_bad_step == 4:
            canned = json.loads(self._generate_canned_valid_response(user_prompt))
            canned["test_cases"][0]["evidence_quotes"] = ["This quote is completely fabricated and absent from text."]
            return json.dumps(canned)

        # Step 5+: Clean valid response
        return self._generate_canned_valid_response(user_prompt)
