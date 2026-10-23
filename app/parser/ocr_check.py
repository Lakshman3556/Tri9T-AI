"""
OCR Cross-Check & Fallback Module (Section 5.7)
Provides optional OCR verification of born-digital text.
If Tesseract binary is not installed, gracefully skips and reports
`{status: 'skipped', reason: 'tesseract binary not found'}`.
Never crashes ingestion on missing external binaries.
"""
import difflib
from typing import Dict, Any, List
import fitz
from app.parser.normalize import normalize_text


def run_ocr_cross_check(doc: fitz.Document, native_page_texts: List[str]) -> Dict[str, Any]:
    """
    Performs rasterization and Tesseract OCR cross-check across document pages.
    Measures difflib string similarity and word-level Jaccard index.
    """
    try:
        import pytesseract
        from PIL import Image
        import io
        
        # Test if tesseract is accessible
        pytesseract.get_tesseract_version()
    except Exception as e:
        return {
            "status": "skipped",
            "reason": f"Tesseract binary not found or not in PATH ({type(e).__name__})",
            "page_similarities": []
        }

    page_results = []
    warnings = []

    for page_idx, page in enumerate(doc):
        native_text = native_page_texts[page_idx] if page_idx < len(native_page_texts) else ""
        norm_native = normalize_text(native_text)

        try:
            # Rasterize page at 200 DPI
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_raw = pytesseract.image_to_string(img)
            norm_ocr = normalize_text(ocr_raw)

            # String difflib ratio
            matcher = difflib.SequenceMatcher(None, norm_native, norm_ocr)
            sim_ratio = round(matcher.ratio(), 4)

            # Word Jaccard
            w_native = set(norm_native.split())
            w_ocr = set(norm_ocr.split())
            jaccard = round(len(w_native & w_ocr) / max(len(w_native | w_ocr), 1), 4)

            if sim_ratio < 0.85:
                warnings.append(f"ocr_native_disagreement on page {page_idx + 1} (similarity {sim_ratio})")

            page_results.append({
                "page": page_idx + 1,
                "similarity_ratio": sim_ratio,
                "jaccard_similarity": jaccard
            })
        except Exception as ocr_err:
            page_results.append({
                "page": page_idx + 1,
                "error": str(ocr_err)
            })

    return {
        "status": "completed",
        "page_similarities": page_results,
        "warnings": warnings
    }
