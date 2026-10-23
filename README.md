# CardioTrack CT-200 Medical Manual QA API

A production-grade backend API built with **FastAPI**, **SQLAlchemy**, and **LLMs** that transforms medical device manuals into structured, versioned hierarchy trees, generates grounded QA test cases, and dynamically detects stale traceability requirements across document revisions.

Candidate: **Lakshman** | GitHub: [@Lakshman3556](https://github.com/Lakshman3556)  
Assignment: Tri9T AI / AffineSurge AI Engineering Internship

---

## 🏛️ Architecture Overview

```
                      ┌───────────────────────────────────────┐
                      │    PDF Manual (v1 / v2 Ingestion)     │
                      └──────────────────┬────────────────────┘
                                         │
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
  Stage A-C: Geometry & Line Classification               Stage B: Ruled Tables
  (Bold + Headings + Margins + Exclusions)                (Cell-clipped words, no comma corruption)
             │                                                       │
             └───────────────────────────┬───────────────────────────┘
                                         │
                                         ▼
                 Stage D-G: Persistent Document AST Tree
                 • Longest prefix parent matching (level_gap handling)
                 • Multiset word coverage validator (catches silent loss)
                 • NFKC Normalization & Ligature resolution
                 • SHA-256 Content Hashing (number-independent)
                                         │
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
┌───────────────────────────┐                           ┌───────────────────────────┐
│     SQLite Relational     │                           │   Versioned Matcher       │
│  (Nodes, Versions, Refs,  │                           │  (5-Pass Top-Down Matching│
│   Immutable Selections)   │                           │   Diffs with Significance)│
└────────────┬──────────────┘                           └─────────────┬─────────────┘
             │                                                        │
             ▼                                                        ▼
┌───────────────────────────┐                           ┌───────────────────────────┐
│  Selection API (Pinned)   │                           │  Dynamic Staleness Engine │
│  • Pinned node snapshots  │                           │  • Evidence quote check   │
│  • Ancestor breadcrumbs   │                           │  • Material threshold diff│
│  • 12,000 char quota      │                           │  • Cross-reference changes│
└────────────┬──────────────┘                           │  • Conflict diagnostics  │
             │                                          └───────────────────────────┘
             ▼                                                        ▲
┌───────────────────────────┐                                         │
│   LLM QA Generation       │                                         │
│   • OpenAI / Groq / Gemini│─────────────────────────────────────────┘
│   • 2-Attempt Repair Loop │
│   • Grounding Verifier    │
│   • Zero-Setup JSON Store │
└───────────────────────────┘
```

---

## 🚀 Quick Start (Zero Setup)

### 1. Prerequisites & Virtual Environment
* Python 3.11+
* Git

```bash
# Clone the repository
git clone https://github.com/Lakshman3556/ct200-qa-api.git
cd ct200-qa-api

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment configuration
cp .env.example .env
```

*(Note: Tesseract OCR is purely optional as cross-check verification. If `tesseract` is absent from PATH, the system records `ocr: {status: 'skipped'}` and deterministically continues without crashing).*

---

### 2. Run the Full End-to-End Demo in One Command

We provide a zero-setup demo script that runs the entire pipeline from scratch against a fresh database using the built-in deterministic Mock LLM:

```bash
python scripts/demo.py
```

This demo runs:
1. Fresh DB schema setup
2. Version 1 PDF manual ingestion
3. Browse top-level sections
4. Version-pinned selection creation for sections `3.2`, `4.2`, `6.1`, `3.3`
5. QA test case generation with grounding checks
6. Fresh retrieval verification against v1
7. Version 2 PDF manual re-ingestion
8. Document diff analysis (`2.1.1.1`, `3.2`, `4.2`, `4.3` modified; `5.3` added; `3.1`, `6.1`, `8.1` unchanged)
9. Dynamic staleness flags (`likely_stale`, `review_recommended`, `fresh`) matching specifications
10. Version-pinning confirmation (selection retains v1 text `40 mmHg` while live node returns `30 mmHg`)

---

### 3. Run the Test Suite

```bash
pytest -v
```
Runs all 19 unit tests covering:
* Duplicate heading node isolation (`4.2` and `7.1`)
* Skipped level parent resolution (`2.1.1.1` under `2.1`)
* Out-of-order sibling tracking (`3.4` before `3.3`)
* Numbered lists not treated as headings (`3.3`)
* 11pt bold heading detection (`3.2`)
* Table cell integrity without comma corruption (`2.1` and `4.2`)
* Ligature expansion and non-breaking hyphen normalization
* Page-break paragraph joining (`3.1`)
* Multiset coverage invariant failure mode
* Golden v1 vs v2 diff
* Immutability of v1 rows after v2 ingestion
* Selection version pinning
* LLM JSON repair loop and grounding checks
* Staleness matrix verification

---

### 4. Running the API Server

```bash
uvicorn app.main:app --reload
```
API Documentation & Interactive Swagger UI is live at: **`http://localhost:8000/docs`**

---

## 📋 End-to-End Walkthrough via cURL

You can execute the entire versioning and staleness workflow via terminal cURL commands:

```bash
# 1. Check API health
curl -X GET http://localhost:8000/health

# 2. Ingest CT-200 Manual Version 1
curl -X POST "http://localhost:8000/ingest/local?path=data/ct200_manual.pdf"

# 3. List top-level sections
curl -X GET "http://localhost:8000/documents/<DOC_ID>/sections"

# 4. Create a version-pinned selection for sections 3.2 and 4.2
curl -X POST "http://localhost:8000/selections" \
     -H "Content-Type: application/json" \
     -d '{"name": "Safety Suite", "items": [{"node_id": "<NODE_3_2_ID>", "version": 1}, {"node_id": "<NODE_4_2_ID>", "version": 1}]}'

# 5. Generate QA Test Cases with LLM
curl -X POST "http://localhost:8000/selections/<SELECTION_ID>/generate?force=false"

# 6. Retrieve test cases against Version 1 (All fresh)
curl -X GET "http://localhost:8000/selections/<SELECTION_ID>/test-cases?against_version=1"

# 7. Re-ingest CT-200 Manual Version 2
curl -X POST "http://localhost:8000/ingest/local?path=data/ct200_manual_v2.pdf&document_id=<DOC_ID>"

# 8. Inspect changes across versions
curl -X GET "http://localhost:8000/documents/<DOC_ID>/changes?from_version=1&to_version=2"

# 9. Retrieve test cases again against Version 2 (Staleness flags visible!)
curl -X GET "http://localhost:8000/selections/<SELECTION_ID>/test-cases?against_version=2"

# 10. Check that original selection still yields pinned v1 text
curl -X GET "http://localhost:8000/selections/<SELECTION_ID>/text"
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./ct200.db` | SQLAlchemy connection string |
| `GENERATION_STORE` | `json` | Storage backend for LLM output: `json` (default) or `mongo` |
| `JSON_STORE_PATH` | `./generations.json` | Path to persistent JSON store file |
| `MONGODB_URI` | `mongodb://localhost:27017`| Mongo connection string (if using `GENERATION_STORE=mongo`) |
| `LLM_PROVIDER` | `mock` | Active provider: `mock`, `groq`, `gemini`, `openrouter` |
| `LLM_API_KEY` | `""` | API key for LLM provider (not required in `mock` mode) |
| `LLM_BASE_URL` | `""` | OpenAI-compatible endpoint URL (e.g. `https://api.groq.com/openai/v1`) |
| `LLM_MODEL` | `mock-model` | Target model name |
| `LLM_MAX_REPAIR_ATTEMPTS` | `2` | Maximum retry attempts for malformed/ungrounded LLM JSON |
| `MAX_SELECTION_CHARS` | `12000` | Max character budget for selection reconstruction (HTTP 413) |

---

## 📁 Repository Layout

```
ct200-qa-api/
├── app/
│   ├── main.py            # FastAPI app & route mounting
│   ├── config.py          # Pydantic Settings
│   ├── db.py              # SQLite engine & PRAGMA configuration
│   ├── orm.py             # SQLAlchemy models (Document, Versions, Nodes, Selections)
│   ├── schemas.py         # Pydantic API schemas
│   ├── parser/
│   │   ├── extract.py     # Main extraction orchestrator
│   │   ├── classify.py    # Line classifier (Bold + Regex + Margin + Table bbox)
│   │   ├── tables.py      # Ruled table extraction via cell-clipped words
│   │   ├── tree.py        # Hierarchy stack builder, prefix matching, flag tracking
│   │   ├── normalize.py   # NFKC normalizer, ligature replacement, hashing
│   │   ├── validate.py    # Invariant validator (word multiset coverage)
│   │   └── ocr_check.py   # Optional OCR verification & fallback
│   ├── services/
│   │   ├── ingest.py      # PDF ingestion & transaction manager
│   │   ├── matching.py    # Layered 5-pass conservative version matcher
│   │   ├── diffing.py     # Word-level diff & lexical significance classifier
│   │   ├── selection.py   # Version-pinned selections & prompt reconstruction
│   │   ├── generation.py  # LLM orchestration, repair loop, grounding check
│   │   └── staleness.py   # Retrieval-time dynamic staleness evaluator
│   ├── llm/
│   │   ├── client.py      # HTTP client & Mock provider
│   │   ├── prompts.py     # Versioned prompt templates (v1)
│   │   └── schemas.py     # Pydantic test case validation schemas
│   ├── stores/
│   │   ├── base.py        # GenerationStore abstract base class
│   │   ├── json_store.py  # Zero-setup JSON file store
│   │   └── mongo_store.py # MongoDB store with automatic JSON fallback
│   └── api/
│       ├── documents.py   # Document lifecycle & whole-diff endpoints
│       ├── nodes.py       # Node detail & node-level diff endpoints
│       ├── search.py      # Normalized text search endpoint
│       ├── selections.py  # Version-pinned selection endpoints
│       ├── generations.py # Test case generation endpoints
│       └── retrieval.py   # Staleness retrieval & impact endpoints
├── scripts/
│   ├── inspect_pdf.py     # PDF empirical inspection script
│   ├── naive_parse_v0.py  # Baseline parser demonstrating failure modes
│   ├── validate_extraction.py # Validates baseline pitfalls
│   └── demo.py            # End-to-end automated demo script
├── tests/
│   ├── test_parser.py     # Parser unit tests (Tests 1 to 12)
│   ├── test_versioning.py # Versioning & golden diff tests (Tests 13, 14, 19)
│   ├── test_selection.py  # Version pinning immutability tests (Test 15)
│   ├── test_generation.py # LLM repair loop and duplicate policy (Tests 16, 17)
│   └── test_staleness.py  # Staleness evaluation matrix (Test 18)
├── data/
│   ├── ct200_manual.pdf   # CT-200 Manual Version 1
│   └── ct200_manual_v2.pdf# CT-200 Manual Version 2
├── docs/
│   ├── APPROACH.md        # Complete engineering approach & Decision Log
│   ├── DEBUG_LOG.md       # Real empirical findings and baseline failure log
│   └── api.http           # Ready-to-run REST Client HTTP requests
├── docker-compose.yml     # Optional MongoDB container
├── requirements.txt       # Pinned Python dependencies
└── README.md
```
