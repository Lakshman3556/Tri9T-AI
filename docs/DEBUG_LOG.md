# Debug Log & Empirical Investigation (CT-200 Manual Parsing)

This document is a chronological, real record of inspection findings, naive baseline failures, root-cause analyses, and verified fixes across the PDF parsing and versioning pipeline.

---

## 1. Initial Document Inspection (Empirical Findings)

Inspection script `scripts/inspect_pdf.py` was executed against `data/ct200_manual.pdf` (v1) and `data/ct200_manual_v2.pdf` (v2).

### 1.1 Physical Layout & Media
* **Source Type:** Born-digital PDF created with vector fonts (`NimbusSans-Regular`, `NimbusSans-Bold`).
* **Page Dimensions:** 420.0 pt × 595.0 pt (single column format).
* **Margins:** Left margin `x0 = 33.0 pt`. Line pitch is approximately 13.2 pt.
* **Embedded Images:** Exactly 0 raster images in both v1 and v2 (`total_images = 0`). Native text extraction preserves 100% fidelity compared to OCR, which would introduce recognition noise.
* **Vector Drawing Operations:** Page 2 contains 78 drawing operations; Page 4 contains 85 drawing operations. These delineate table borders.

### 1.2 Font Size & Weight Map
| Element | Measured Size / Weight | Observation |
| :--- | :--- | :--- |
| **Document Title** | 22.0 pt Bold (3 lines on page 1) | Single logical title split across 3 consecutive spans. |
| **Level-1 Headings (1..8)** | 16.5 pt Bold | Consistently formatted at margin `x0 = 33.0`. |
| **Level-2 Headings (x.y)** | 12.87 pt Bold | Standard for 1.1, 1.2, 2.1, 2.2, 3.1, 3.3, 3.4, etc. |
| **3.2 Cuff Inflation Sequence** | **11.0 pt Bold** | **Anomaly:** Exactly the same font size as body text. A size-thresholded parser drops this heading into body text. |
| **2.1.1.1 Battery Life...** | **11.0 pt Bold** | **Anomaly:** Level-4 heading formatted at body size (11 pt). Skips Level-3 (`2.1.1` does not exist). |
| **Table Headers** | 11.0 pt Bold | Inside table cells (`Parameter`, `Value`, `Code`, `Meaning`). Bold detectors without bounding-box checks falsely treat them as section titles. |
| **Body Paragraphs** | 11.0 pt Regular | Left margin `x0 = 33.0`. Line pitch ~13.2 pt. |
| **List Items (Section 3.3)** | 11.0 pt Regular | Indented at `x0 = 50.8 pt`. Line wrapped continuation at `x0 = 63.0 pt`. Numbered `1. Normal ... 5. Hypertensive Crisis`. |

---

## 2. Naive Baseline (v0) Failures & Diagnostics

The baseline naive parser (`scripts/naive_parse_v0.py`) was evaluated via `scripts/validate_extraction.py`. The resulting failure log:

```text
--- Naive v0 Extraction Failure Report ---
  • FAIL [I2]: Section '3.2' is completely missing because its heading is 11pt (demoted to body).
  • FAIL [I2/I3]: Section '2.1.1.1' is missing because its heading is 11pt.
  • FAIL [I8]: Section 4.2 table text is fragmented or missing key error rows.
  • FAIL [I9]: Unnormalized Unicode ligatures (fi/fl/ff) exist in extracted text; search will fail.
  • FAIL: Expected 27 section nodes in v1, but naive parser found 22.
```

### Root Cause Diagnostics
1. **Size-Only Classification Failure (I2):**
   Sections `3.2` and `2.1.1.1` are 11.0 pt bold. Setting a heading threshold like `size > 12.0` misses them completely, causing them to disappear into the preceding node's body text.
2. **Regex-Only Classification Failure (I6):**
   Section 3.3 contains numbered list items (`1. Normal`, `2. Elevated`, etc.). Matching `^\d+\.` without checking font weight (regular vs bold) and indentation (`x0 > margin + 5`) causes lists to be misclassified as top-level H1 sections.
3. **Table Fragmentation (I8):**
   PyMuPDF's default `find_tables()` text extractor splits words across cells, leaving stray punctuation (e.g. `'1 .5 seconds'`, `'0 \u2013299 mmHg'`).
4. **Ligature Pollution (I9):**
   Text contains 93 Unicode ligatures (`fi` = `U+FB01`, `ff` = `U+FB00`, `fl` = `U+FB02`) and non-breaking hyphens (`U+2011`). Substring search for `"profile"` fails because the document text has `"pro\uFB01le"`.
5. **Page-Break Splitting (I10/I11):**
   Section 3.1 splits across pages 2 and 3. Without cross-page state retention, page breaks introduce spurious word joins or orphans.

---

## 3. Engineering Fixes Implemented in Production Parser
1. **Line Classifier:** Compound condition: `bold AND HEAD_RE matches AND x0 <= margin + 3 AND not inside table_bbox`.
2. **Table Extraction:** Cell-clipped word grouping (`page.get_text('words', clip=cell_rect)`) sorted by Y then X.
3. **Unicode Normalization:** Full `unicodedata.normalize('NFKC')` + non-breaking hyphen replacement (`\u2011` -> `-`).
4. **Hierarchy Stack:** Longest numeric prefix ancestor resolution with `level_gap` and `out_of_order` flag tracking.
