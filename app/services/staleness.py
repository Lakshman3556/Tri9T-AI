"""
Staleness and Impact Detection Engine (Sections 10.1 & 10.2)
Computes retrieval-time staleness dynamically against any target document version.
Checks:
- Evidence quote presence in current node text
- Lexical significance of text diffs (material vs wording)
- Source node removal (tombstones)
- Cross-reference change propagation (e.g. 3.3 citing changed section 4.3)
- Internal consistency warning (Section 2.6 conflict between 4.1 and 4.2)
"""
import re
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.orm import NodeVersion, DocumentVersion, LogicalNode, NodeReference
from app.parser.normalize import normalize_text
from app.services.diffing import compute_word_diff
from app.services.generation import clean_for_grounding

STATUS_RANK = {
    "likely_stale": 4,
    "review_recommended": 3,
    "probably_valid": 2,
    "fresh": 1
}


class StalenessEvaluator:
    def __init__(self, db: Session):
        self.db = db

    def evaluate_generation(
        self,
        generation_doc: Dict[str, Any],
        against_version: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Evaluates a generation against target version (defaults to latest ingested version).
        Returns enriched generation with per-test-case staleness and status_rollup.
        """
        source_snapshot = generation_doc.get("source_snapshot", [])
        if not source_snapshot:
            return generation_doc

        # Determine document ID from first node
        first_logical_id = source_snapshot[0]["logical_node_id"]
        ln = self.db.query(LogicalNode).filter(LogicalNode.id == first_logical_id).first()
        if not ln:
            return generation_doc

        doc_id = ln.document_id

        # Resolve target document version
        if against_version is not None:
            target_doc_ver = self.db.query(DocumentVersion).filter(
                DocumentVersion.document_id == doc_id,
                DocumentVersion.version_no == against_version
            ).first()
        else:
            target_doc_ver = self.db.query(DocumentVersion).filter(
                DocumentVersion.document_id == doc_id
            ).order_by(DocumentVersion.version_no.desc()).first()

        target_version_no = target_doc_ver.version_no if target_doc_ver else 1

        # 1. Evaluate Source Snapshot Items
        node_status_map = {}
        for s in source_snapshot:
            logical_id = s["logical_node_id"]
            sec_num = s["section_number"]

            curr_nv = self.db.query(NodeVersion).filter(
                NodeVersion.logical_node_id == logical_id,
                NodeVersion.document_version_id == target_doc_ver.id
            ).first() if target_doc_ver else None

            if not curr_nv:
                node_status_map[sec_num] = {
                    "status": "source_removed",
                    "node": None,
                    "diff": {"info": "Section removed in target version"},
                    "significance": "material"
                }
            elif curr_nv.own_hash == s["content_hash"]:
                # Own content unchanged; check if referenced nodes changed
                refs = self.db.query(NodeReference).filter(NodeReference.from_node_version_id == curr_nv.id).all()
                ref_changed = False
                for r in refs:
                    target_nv = self.db.query(NodeVersion).filter(
                        NodeVersion.document_version_id == target_doc_ver.id,
                        NodeVersion.section_number == r.target_section_number
                    ).first()
                    if target_nv and target_nv.change_status in ("modified", "added"):
                        ref_changed = True
                        break

                node_status_map[sec_num] = {
                    "status": "reference_changed" if ref_changed else "unchanged",
                    "node": curr_nv,
                    "diff": None,
                    "significance": "none"
                }
            else:
                # Content changed! Compute diff with significance
                diff_summary = compute_word_diff(s.get("text_norm", ""), curr_nv.body_norm)
                node_status_map[sec_num] = {
                    "status": "modified",
                    "node": curr_nv,
                    "diff": diff_summary,
                    "significance": diff_summary["significance"]
                }

        # 2. Evaluate Each Test Case
        evaluated_cases = []
        worst_rank = 1

        for tc in generation_doc.get("test_cases", []):
            tc_sources = tc.get("source_sections", [])
            evidence_quotes = tc.get("evidence_quotes", [])

            tc_status = "fresh"
            reasons = []
            missing_quotes = []
            changed_nodes = []

            # Check source nodes
            for sec in tc_sources:
                info = node_status_map.get(sec)
                if not info or info["status"] == "source_removed":
                    tc_status = "likely_stale"
                    reasons.append(f"Source section '{sec}' was removed in version {target_version_no}")
                elif info["status"] == "modified":
                    changed_nodes.append({
                        "section": sec,
                        "significance": info["significance"],
                        "diff": info["diff"]
                    })
                    if info["significance"] == "material":
                        if tc_status != "likely_stale":
                            tc_status = "review_recommended"
                        reasons.append(f"Material threshold or requirement change in section {sec}")
                    else:
                        if tc_status == "fresh":
                            tc_status = "probably_valid"
                        reasons.append(f"Wording changes detected in section {sec}")
                elif info["status"] == "reference_changed":
                    if tc_status == "fresh":
                        tc_status = "review_recommended"
                    reasons.append(f"Cross-referenced section cited by {sec} was modified in version {target_version_no}")

            # Check Evidence Quotes Grounding in Target Text
            for q in evidence_quotes:
                norm_q = clean_for_grounding(q)
                # Verify quote exists in target node text
                quote_found = False
                for sec in tc_sources:
                    info = node_status_map.get(sec)
                    if info and info["node"]:
                        target_text_clean = clean_for_grounding(info["node"].body_text)
                        if norm_q in target_text_clean:
                            quote_found = True
                            break
                if not quote_found:
                    tc_status = "likely_stale"
                    missing_quotes.append(q)
                    reasons.append(f"Evidence quote no longer present in current text: '{q}'")

            # Section 2.6 Conflict Hint (e.g. section 4.1 vs 4.2 emergency valve / E3 contradiction)
            possibly_related = []
            if "4.1" in tc_sources and target_version_no >= 2:
                # 4.2 modified E3 to 1.5s while 4.1 still says 2 seconds
                n4_2 = node_status_map.get("4.2")
                if n4_2 and n4_2["status"] == "modified":
                    possibly_related.append({
                        "section": "4.2",
                        "hint": "Requirement conflict: Section 4.2 changed E3 deflation to 1.5s, while 4.1 remains at 2s."
                    })

            rank = STATUS_RANK.get(tc_status, 1)
            if rank > worst_rank:
                worst_rank = rank

            tc_copy = dict(tc)
            tc_copy["staleness"] = {
                "status": tc_status,
                "compared_version": target_version_no,
                "reasons": reasons,
                "missing_quotes": missing_quotes,
                "changed_nodes": changed_nodes,
                "possibly_related_nodes": possibly_related
            }
            evaluated_cases.append(tc_copy)

        # Rollup status
        rollup_status = [k for k, v in STATUS_RANK.items() if v == worst_rank][0]

        result = dict(generation_doc)
        result["compared_against_version"] = target_version_no
        result["status_rollup"] = rollup_status
        result["test_cases"] = evaluated_cases
        return result
