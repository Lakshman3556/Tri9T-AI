# Engineering Approach Document: CT-200 Medical Manual QA API

Candidate: **Lakshman** | GitHub: [@Lakshman3556](https://github.com/Lakshman3556)  
Project: CardioTrack CT-200 Technical Manual Extraction, Versioning & Staleness Pipeline

---

## 1. Document Parsing Strategy & Technical Justification

### 1.1 Born-Digital PDFs vs. Pure OCR
The assignment explicitly requires an OCR-based or document understanding extraction pipeline. When inspecting `data/ct200_manual.pdf` (v1, 6 pages) and `data/ct200_manual_v2.pdf` (v2, 7 pages) with `scripts/inspect_pdf.py`, empirical measurement revealed:
* **Embedded Images:** Exactly `0` raster images in both v1 and v2.
* **Vector Fonts:** All text is rendered using embedded fonts (`NimbusSans-Regular`, `NimbusSans-Bold`).
* **Text Layer:** 100% of characters reside in a clean native PDF stream.
* **Vector Geometry:** Table borders are drawn with vector drawing paths (78 drawing operations on page 2; 85 on page 4).

**Our Architecture Choice:**
We selected a **native-first extraction pipeline powered by PyMuPDF (`fitz`)**, combined with an **optional OCR cross-check (`pytesseract`)**. 
Applying pure OCR to a clean born-digital PDF degrades recognition accuracy: OCR introduces character misidentifications (e.g., confusing `1` and `l`, dropping punctuation, corrupting decimals in medical ranges like `0.5 mmHg`). 

However, to respect the regulatory OCR requirement:
1. We implemented `app/parser/ocr_check.py`, which rasterizes pages at 200 DPI and computes string difflib similarity and word-level Jaccard against native text.
2. If native text contains fewer than 20 characters per page (scanned documents), the pipeline automatically switches to OCR word boxes via `pytesseract.image_to_data`.
3. If `tesseract` is absent from the host environment, the system gracefully logs `ocr: {status: 'skipped'}` and continues without crashing.

### 1.2 Alternatives Considered and Rejected
* **Docling / Marker / Unstructured:** While capable, these frameworks introduce heavy deep learning dependencies (PyTorch, layout models) that are non-deterministic, slow to install in constrained environments, and frequently produce unpredictable heading nestings on structured technical manuals.
* **pdfplumber default tables:** Measured inspection showed `pdfplumber.extract_tables()` produced phantom sub-tables (e.g. splitting `['Pressure', 'range']` and `['0–', '299', 'mmHg']`).
* **PyMuPDF default cell text:** Default PyMuPDF cell extraction corrupted commas and numbers (returning `'Aborts measurement displays E1\n,'` and `'1 .5 seconds'` because commas and periods were distinct spans). We solved this by clipping words to cell bounding boxes and sorting them geometrically.

---

## 2. Hierarchy Reconstruction Strategy

Hierarchy reconstruction relies on four strict criteria:
1. **Margin Anchor:** Dynamic detection of the body margin `x0 = min(line_x0)` (measured at `33.0 pt`).
2. **Compound Heading Rule:** A line is a heading if and only if:
   $$\text{bold} \land \text{HEAD\_RE} \land (x_0 \le \text{margin} + 3.0\text{ pt}) \land (\text{bbox} \notin \text{table\_bbox})$$
3. **Declared Depth:** Count of dotted parts (e.g. `2.1.1.1` $\to$ level 4; `3` $\to$ level 1).
4. **Persistent Longest-Prefix Parent Resolution:**
   Rather than resetting state per page, the parser maintains an ongoing document tree. When heading `2.1.1.1` arrives, parent search tests candidate prefixes in descending order: `2.1.1`, then `2.1`, then `2`. It immediately resolves `2.1` as the parent, declares `tree_depth = 3`, and flags `level_gap`.

---

## 3. Structural Irregularities Discovered by Inspection

*(Note: The assignment brief states "handle every irregularity listed above", but the original problem description had no explicit list. We discovered these irregularities through empirical PDF inspection).*

| ID | Structural Irregularity | Occurrence in PDF | Failure of Naive Baseline | Implemented Engineering Solution |
| :--- | :--- | :--- | :--- | :--- |
| **I1** | **Multi-line Title** | Page 1 (3 lines, 22pt bold) | Created 3 bogus root nodes or truncated title | Merged consecutive 22pt bold lines before first heading into single root node. |
| **I2** | **Heading Font Anomaly** | `3.2` & `2.1.1.1` (11.0 pt bold) | Size-thresholded parser dropped them into body text | Detected via `bold + HEAD_RE + margin + not_in_table`; logged `size_mismatch` warning. |
| **I3** | **Skipped Hierarchy Level** | `2.1` followed by `2.1.1.1` (no `2.1.1`) | Orphaned node or crashed stack | Resolved parent via longest prefix (`2.1`), recorded `level_declared = 4`, `tree_depth = 3`, flagged `level_gap`. |
| **I4** | **Out-of-Order Siblings** | Section `3.4` appears before `3.3` on page 3 | Re-sorted or mis-parented under 3.4 | Preserved physical reading order in `doc_order`; flagged `out_of_order` on 3.3. |
| **I5** | **Duplicate Heading Text** | `"Error Codes"` at `4.2` and `7.1` | Overwritten in title-keyed dictionaries | Nodes keyed by UUID; parent-aware matching prevents cross-coupling; flagged `duplicate_title`. |
| **I6** | **Numbered List vs. H1 Headings** | Section `3.3` (`1. Normal` to `5. Hypertensive Crisis`) | Regex parser created 5 fake H1 top-level sections | Enforced bold weight and margin: list items are regular weight and indented (`x0 > margin + 5`). |
| **I7** | **Cross-References in Prose** | `3.3` ("see 2.1, 4.3"), `7.1` ("Section 4.2") | Treated as headings or ignored | Extracted into `node_references` table for downstream staleness propagation. |
| **I8** | **Ruled Tables with Multi-line Cells** | `2.1` Specifications, `4.2` Error Codes | Header read as heading; commas detached | Ruled table geometry with cell-clipped words; formatted as pipe-delimited table blocks. |
| **I9** | **Unicode Ligatures & Hyphens** | 93 ligatures (`\ufb01`, `\ufb02`, `\ufb00`), non-breaking hyphens | Substring search for `"profile"` fails | `unicodedata.normalize('NFKC')` + non-breaking hyphen translation (`\u2011` $\to$ `-`). |
| **I10** | **Headings Stranded at Page Bottom** | Sections `2`, `4`, `5`, `7` at bottom of page | Headings glued to next page text or orphaned | Persistent parser stack across pages; subsequent lines belong to active heading. |
| **I11** | **Paragraph Split Across Page Break** | `3.1` (p2/p3), `6.1`, `8.1` | False v1/v2 diffs due to shifting page boundaries | Appended across page break with single space; collapsed whitespace hashing. |
| **I12** | **Heading-Only Parent Sections** | Sections `2, 3, 4, 5, 6, 7, 8` | Empty body nodes dropped or assigned child text | Preserved as valid structural nodes with empty own body; `subtree_hash` covers children. |
| **I13** | **Content Anomaly in Source** | `6.2` reads "Anthropic recommends recalibration" | Silently dropped or altered | Preserved verbatim; LLM prompt forbids hallucinating manufacturer names. |
| **I14** | **Wrapped Numbered List Items** | `3.3` item 5 continuation lines | Extra bogus list item created | Continuation lines (`LIST_CONT`, indented, no number) appended to active list item. |

---

## 4. Naive Baseline Failures vs. Production Results

The baseline naive parser (`scripts/naive_parse_v0.py`) was evaluated via `scripts/validate_extraction.py`. The real failure output:

```text
--- Naive v0 Extraction Failure Report ---
  • FAIL [I2]: Section '3.2' is completely missing because its heading is 11pt (demoted to body).
  • FAIL [I2/I3]: Section '2.1.1.1' is missing because its heading is 11pt.
  • FAIL [I8]: Section 4.2 table text is fragmented or missing key error rows.
  • FAIL [I9]: Unnormalized Unicode ligatures (fi/fl/ff) exist in extracted text; search will fail.
  • FAIL: Expected 27 section nodes in v1, but naive parser found 22.
```

### Quantitative Comparison:
| Metric | Naive Baseline (v0) | Production Pipeline |
| :--- | :--- | :--- |
| **Total Section Nodes (v1)** | 22 (missed 3.2, 2.1.1.1, etc.) | **28 (27 sections + 1 root)** ✅ |
| **Total Section Nodes (v2)** | 23 | **29 (28 sections + 1 root)** ✅ |
| **Table Extraction** | Raw text stream with broken commas | **Structured cell-clipped rows** ✅ |
| **Search Hit for "profile"** | Failed (blocked by `\ufb01` ligature) | **100% hit rate on normalized text** ✅ |
| **Multiset Word Coverage** | Failed (dropped ~180 words) | **Invariant Validated (0 words dropped)** ✅ |

---

## 5. Data Model & Entity Relationships

The relational design enforces a fundamental separation between **Logical Identity** (stable across versions) and **Node Version** (immutable snapshot):

```
┌────────────────────┐          ┌─────────────────────────┐
│     documents      │1        *│    document_versions    │
│────────────────────│──────────│─────────────────────────│
│ id (UUID)          │          │ id (UUID)               │
│ name               │          │ document_id (FK)        │
│ created_at         │          │ version_no (1, 2, ...)  │
└─────────┬──────────┘          │ file_sha256             │
          │                     │ parse_status            │
          │                     │ parse_report (JSON)     │
          │1                    └────────────┬────────────┘
          │                                  │1
          ▼*                                 ▼*
┌────────────────────┐          ┌─────────────────────────┐
│   logical_nodes    │1        *│      node_versions      │
│────────────────────│──────────│─────────────────────────│
│ id (UUID)          │          │ id (UUID)               │
│ document_id (FK)   │          │ logical_node_id (FK)    │
│ canonical_number   │          │ document_version_id (FK)│
│ canonical_title    │          │ parent_node_version_id  │
└────────────────────┘          │ section_number          │
                                │ heading, heading_norm   │
                                │ level_declared, depth   │
                                │ body_text, body_norm    │
                                │ own_hash, subtree_hash  │
                                │ change_status           │
                                └────────────┬────────────┘
                                             │1
                                             ▼*
┌────────────────────┐1        *┌─────────────────────────┐
│     selections     │──────────│     selection_items     │
│────────────────────│          │─────────────────────────│
│ id (UUID)          │          │ selection_id (FK)       │
│ document_id (FK)   │          │ node_version_id (FK)    │
│ name               │          │ logical_node_id (FK)    │
│ fingerprint        │          │ pinned_hash             │
└────────────────────┘          └─────────────────────────┘
```

* **Selections are Immutable:** No `PUT` or `PATCH`. If a user modifies a selection, a new selection record is created.
* **Version-Pinned Selection Items:** Pin to specific `node_version_id` rows. When document v2 is ingested, existing selections continue to resolve to the exact text of v1.

---

## 6. Document Versioning & Matching Strategy

Re-ingesting `ct200_manual_v2.pdf` executes a **conservative 5-pass matcher** (`app/services/matching.py`) that matches nodes from top to bottom:

1. **Pass 1: Exact Key:** Same `section_number` AND same `heading_norm` under matched parents $\to$ same logical node (`unchanged` if `own_hash` identical, else `modified`).
2. **Pass 2: Title Under Matched Parent:** Same `heading_norm` under matched parents, differing section number $\to$ `renumbered`.
3. **Pass 3: Unique Hash Match:** Unmatched nodes sharing an identical `own_hash` $\to$ `moved` or `renumbered`.
4. **Pass 4: Mutual Best Fuzzy Match:** `rapidfuzz.token_set_ratio(heading) >= 90` AND `difflib.body_ratio >= 0.6` $\to$ `modified` (`change_basis = 'fuzzy'`).
5. **Pass 5: Leftovers:** Unmatched new nodes $\to$ `added`; unmatched old nodes $\to$ `removed` (tombstone). Never force a match.

### Golden v1 to v2 Results (Verified by Test 13):
* **Modified:** `2.1.1.1` (cycle threshold 300 $\to$ 250, low battery 15% $\to$ 10%), `3.2` (inflation increment 40 $\to$ 30 mmHg), `4.2` (E3 deflation 2s $\to$ 1.5s, row E6 added), `4.3` (`E1-E5` $\to$ `E1-E6`).
* **Added:** `5.3 Data Export` (firmware 1.4 CSV export).
* **Unchanged:** All other 22 sections + root (including traps `3.1`, `6.1`, and `8.1`).

---

## 7. LLM Prompt Design, Grounding & Robustness

### 7.1 Grounding & Anti-Hallucination Measures
* **System Prompt:** Specifies that the technical excerpt is strict DATA, not instructions.
* **Verbatim Evidence Quotes:** For every test case, the LLM must return 1 to 3 exact substrings (`evidence_quotes`, min 12 characters).
* **Post-Generation Grounding Validator:** The backend verifies that every evidence quote is an exact normalized substring of the source excerpt. If a model hallucinates a threshold or quotes absent text, that test case is automatically dropped.

### 7.2 Handling Malformed Responses (Table 9.5 Behavior)
1. **Markdown Fences:** Fences (` ```json `) are stripped and the first balanced `{...}` is parsed.
2. **Syntax / Schema Errors:** Triggers a 2-step repair retry sending the parse error back to the model.
3. **Persistent Garbage:** If all attempts fail, the generation is persisted with `status: "failed"` along with the full audit log of raw attempts, and the API returns **HTTP 502 Bad Gateway**. Unvalidated test cases are **never** returned to the user.

### 7.3 Duplicate Submission Policy
* Keyed on `(selection_fingerprint, prompt_version, model)`.
* Subsequent submissions return the completed generation with `reused: true` without invoking the LLM.
* Adding `?force=true` generates a new record that marks the earlier generation via `supersedes`.
* Per-selection in-process `asyncio.Lock` prevents race conditions from double-clicks.

---

## 8. Staleness & Impact Detection (Retrieval Time)

Staleness is **never stored as a static flag**; it is dynamically evaluated at query time against the requested target version (`?against_version=latest`):

$$\text{Test Case Status} = \begin{cases} 
\text{likely\_stale} & \text{if cited quote is missing or source node was removed} \\
\text{review\_recommended} & \text{if source had material change or cross-referenced section changed} \\
\text{probably\_valid} & \text{if source only had cosmetic wording changes} \\
\text{fresh} & \text{if source text and references are unchanged}
\end{cases}$$

### Significance Classifier:
* **Material Change:** Any diff token containing a digit, a medical/physical unit (`mmHg`, `seconds`, `%`, `bpm`), an identifier (`E1`..`E6`), or a safety modal (`must`, `shall`, `exceeds`, `within`).
* **Wording Change:** Minor grammatical or non-threshold phrasing adjustments.

---

## 9. Decision Log (Required Candidate Responses)

### 1. What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?
**Lakshman:** The staleness detection engine is the most vulnerable to silent false positives. It evaluates staleness by checking if the specific text cited by a test case still exists in the latest document version. However, it cannot automatically detect cross-section semantic contradictions. For example, in Version 2, Section `4.1` remains completely unchanged and states that the emergency valve auto-deflates within **2 seconds**, while Section `4.2` was updated to state that Error Code `E3` auto-deflates within **1.5 seconds**. A test case generated against Section 4.1 will report `fresh` because its cited text hasn't changed, even though the manual is now internally contradictory. To mitigate this, I implemented a `possibly_related_nodes` diagnostic that alerts the user when another section sharing the same error identifiers (`E3`) or units (`seconds`) has changed.

### 2. Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?
**Lakshman:** I chose a heuristic lexical significance classifier (checking digits, units, and modal keywords) rather than building a semantic AST parser for medical requirement logic. What would break first in production is subtle phrasing reversals that don't alter keywords—such as an engineering update that inverts a requirement using descriptive prose without trigger words (e.g., replacing *"cuff must deflate"* with an indirect statement). Additionally, in high-volume production, SQLite table locks during concurrent PDF ingestions and the in-process `asyncio.Lock` for LLM deduplication would need to be replaced with PostgreSQL and a distributed Redis/Celery queue.

### 3. Name one input (to your parser, your versioning matcher, or your LLM call) that you did not handle, and what your system does when it sees it.
**Lakshman:** For the PDF parser, I did not implement support for multi-column layouts or complex rotated graphical schematics. If a two-column manual is uploaded, the parser detects that text bounding boxes cross column gutters and marks the document with `parse_status = "needs_review"` and emits an `unsupported_block` warning rather than silently scrambling the reading order. For the LLM generation endpoint, if a selection's combined text exceeds 12,000 characters, rather than silently truncating the prompt and losing vital requirements, the API explicitly rejects the request with **HTTP 413 Payload Too Large**.

---

## 10. What I Would Do With More Time
1. **Full Text Search Indexing:** Upgrade SQLite `LIKE` queries to SQLite `FTS5` virtual tables with BM25 ranking.
2. **Distributed Job Queue:** Move PDF extraction and LLM repair loops to asynchronous Celery/Redis tasks with webhook notifications.
3. **Visual Regression Overlays:** Generate automated PNG diff overlays highlighting changed paragraphs directly on the PDF canvas.
4. **Graph-Based Requirement Modeling:** Build a knowledge graph linking safety requirements across sections to automatically flag contradictions like the Section 4.1 vs 4.2 timing conflict.
