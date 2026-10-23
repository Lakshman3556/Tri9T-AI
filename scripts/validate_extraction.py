"""
Validation script that evaluates parser outputs against ground truth invariants
and explicitly exposes extraction failures for debugging logs.
"""
from pathlib import Path
from scripts.naive_parse_v0 import naive_parse


def validate_v0_failures():
    base_dir = Path(__file__).parent.parent
    v1_pdf = base_dir / "data" / "ct200_manual.pdf"
    
    sections = naive_parse(v1_pdf)
    section_map = {s["number"]: s for s in sections if s["number"] != "0"}
    
    failures = []

    # Check 1: 3.2 Cuff Inflation Sequence (11 pt bold - missing in size-thresholded parser)
    if "3.2" not in section_map:
        failures.append("FAIL [I2]: Section '3.2' is completely missing because its heading is 11pt (demoted to body).")
    else:
        failures.append("PASS: Section 3.2 found.")

    # Check 2: 2.1.1.1 Battery Life Under Typical Use (11 pt bold - missing)
    if "2.1.1.1" not in section_map:
        failures.append("FAIL [I2/I3]: Section '2.1.1.1' is missing because its heading is 11pt.")
    else:
        failures.append("PASS: Section 2.1.1.1 found.")

    # Check 3: Check for table corruption in 2.1 and 4.2
    s4_2 = section_map.get("4.2")
    if s4_2:
        if "Auto-deflates within 2 seconds" not in s4_2["body"] or "E3" not in s4_2["body"]:
            failures.append("FAIL [I8]: Section 4.2 table text is fragmented or missing key error rows.")
        else:
            failures.append("PASS: Section 4.2 has raw text, but table structure is lost as pipe rows.")
    else:
        failures.append("FAIL [I8]: Section 4.2 Error Codes is missing.")

    # Check 4: Check if ligatures are intact or un-normalized
    combined_body = "".join(s["body"] for s in sections)
    if any(c in combined_body for c in ["\ufb00", "\ufb01", "\ufb02"]):
        failures.append("FAIL [I9]: Unnormalized Unicode ligatures (fi/fl/ff) exist in extracted text; search will fail.")
    else:
        failures.append("PASS: No raw ligatures.")

    # Check 5: Total section count vs expected 27 sections
    if len(section_map) != 27:
        failures.append(f"FAIL: Expected 27 section nodes in v1, but naive parser found {len(section_map)}.")
    else:
        failures.append("PASS: Exactly 27 sections found.")

    print("\n--- Naive v0 Extraction Failure Report ---")
    for f in failures:
        print(f"  • {f}")
    
    return failures


if __name__ == "__main__":
    validate_v0_failures()
