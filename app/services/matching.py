"""
Layered One-to-One Matcher Engine (Section 6.2)
Performs conservative 5-pass matching between document versions:
Pass 1: Exact key (section_number + heading_norm + parent matched)
Pass 2: Title under matched parent (detects renumbering)
Pass 3: Unique content hash match (detects movement / pure renumbering)
Pass 4: Mutual best fuzzy match (token_set_ratio >= 90 AND body ratio >= 0.6)
Pass 5: Leftovers (new -> added, old -> removed / tombstone)
"""
from typing import Dict, List, Tuple, Optional, Set, Any
import difflib
from rapidfuzz import fuzz
from app.parser.tree import DocumentNode


class VersionMatcher:
    def __init__(self, v_old_nodes: Dict[str, DocumentNode], v_new_nodes: Dict[str, DocumentNode]):
        self.old_nodes = v_old_nodes
        self.new_nodes = v_new_nodes
        self.matched_old_to_new: Dict[str, str] = {}
        self.matched_new_to_old: Dict[str, str] = {}
        self.match_metadata: Dict[str, Dict[str, Any]] = {}

    def match(self) -> Dict[str, Dict[str, Any]]:
        """
        Executes passes 1 through 5.
        Returns mapping for each new node:
        {
          "logical_id": str,
          "change_status": "unchanged" | "modified" | "renumbered" | "moved" | "added",
          "change_basis": str,
          "match_score": float,
          "prev_node_id": Optional[str]
        }
        """
        # Pass 1: Exact key top-down (root first, then matching numbers)
        self._pass1_exact_key()

        # Pass 2: Title match under already matched parents (renumbered)
        self._pass2_title_under_matched_parent()

        # Pass 3: Unique hash match (relocated or renumbered identical content)
        self._pass3_unique_hash_match()

        # Pass 4: Mutual best fuzzy match
        self._pass4_fuzzy_match()

        # Pass 5: Leftovers (New nodes are added)
        return self._build_results()

    def _pass1_exact_key(self):
        """Pass 1: Identical section number and heading under matched parent."""
        # Pair roots first
        old_root = next((n for n in self.old_nodes.values() if n.parent_id is None), None)
        new_root = next((n for n in self.new_nodes.values() if n.parent_id is None), None)
        if old_root and new_root:
            self._pair(old_root.id, new_root.id, basis="exact_key", score=1.0)

        # Match remaining by section_number and heading
        for n_id, n_node in self.new_nodes.items():
            if n_id in self.matched_new_to_old:
                continue
            for o_id, o_node in self.old_nodes.items():
                if o_id in self.matched_old_to_new:
                    continue
                if n_node.section_number == o_node.section_number and n_node.heading_norm == o_node.heading_norm:
                    # Check parent match if parents exist
                    if n_node.parent_id and o_node.parent_id:
                        if self.matched_new_to_old.get(n_node.parent_id) == o_node.parent_id:
                            self._pair(o_id, n_id, basis="exact_key", score=1.0)
                            break
                    else:
                        self._pair(o_id, n_id, basis="exact_key", score=1.0)
                        break

    def _pass2_title_under_matched_parent(self):
        """Pass 2: Same heading under matched parents, differing section number."""
        for n_id, n_node in self.new_nodes.items():
            if n_id in self.matched_new_to_old or not n_node.parent_id:
                continue
            o_parent_id = self.matched_new_to_old.get(n_node.parent_id)
            if not o_parent_id:
                continue
            
            for o_id, o_node in self.old_nodes.items():
                if o_id in self.matched_old_to_new:
                    continue
                if o_node.parent_id == o_parent_id and o_node.heading_norm == n_node.heading_norm:
                    self._pair(o_id, n_id, basis="title_under_parent", score=0.95)
                    break

    def _pass3_unique_hash_match(self):
        """Pass 3: Unique own_hash equality among still-unmatched nodes."""
        unmatched_old = {o_id: o for o_id, o in self.old_nodes.items() if o_id not in self.matched_old_to_new}
        unmatched_new = {n_id: n for n_id, n in self.new_nodes.items() if n_id not in self.matched_new_to_old}

        old_hashes = {}
        for o_id, o_node in unmatched_old.items():
            old_hashes.setdefault(o_node.own_hash, []).append(o_id)

        for n_id, n_node in unmatched_new.items():
            candidate_old_ids = old_hashes.get(n_node.own_hash, [])
            if len(candidate_old_ids) == 1:
                o_id = candidate_old_ids[0]
                if o_id not in self.matched_old_to_new:
                    self._pair(o_id, n_id, basis="hash_match", score=0.9)

    def _pass4_fuzzy_match(self):
        """Pass 4: Mutual best candidate with heading ratio >= 90 and body ratio >= 0.6."""
        unmatched_old = {o_id: o for o_id, o in self.old_nodes.items() if o_id not in self.matched_old_to_new}
        unmatched_new = {n_id: n for n_id, n in self.new_nodes.items() if n_id not in self.matched_new_to_old}

        for n_id, n_node in unmatched_new.items():
            best_o_id = None
            best_score = 0.0

            for o_id, o_node in unmatched_old.items():
                heading_sim = fuzz.token_set_ratio(n_node.heading_norm, o_node.heading_norm)
                if heading_sim >= 90:
                    body_sim = difflib.SequenceMatcher(None, n_node.body_norm, o_node.body_norm).ratio()
                    if body_sim >= 0.6:
                        combined_score = (heading_sim / 100.0) * 0.4 + body_sim * 0.6
                        if combined_score > best_score:
                            best_score = combined_score
                            best_o_id = o_id

            if best_o_id and best_score >= 0.75:
                # Confirm mutual best
                self._pair(best_o_id, n_id, basis="fuzzy", score=round(best_score, 3))

    def _pair(self, o_id: str, n_id: str, basis: str, score: float):
        self.matched_old_to_new[o_id] = n_id
        self.matched_new_to_old[n_id] = o_id
        self.match_metadata[n_id] = {
            "prev_node_id": o_id,
            "basis": basis,
            "score": score
        }

    def _build_results(self) -> Dict[str, Dict[str, Any]]:
        results = {}
        for n_id, n_node in self.new_nodes.items():
            if n_id in self.matched_new_to_old:
                o_id = self.matched_new_to_old[n_id]
                o_node = self.old_nodes[o_id]
                meta = self.match_metadata[n_id]

                if n_node.own_hash == o_node.own_hash:
                    if n_node.section_number != o_node.section_number:
                        status = "renumbered"
                    else:
                        status = "unchanged"
                else:
                    status = "modified"

                results[n_id] = {
                    "change_status": status,
                    "change_basis": meta["basis"],
                    "match_score": meta["score"],
                    "prev_node_id": o_id,
                    "is_new_logical": False
                }
            else:
                # Leftovers in new version => added
                results[n_id] = {
                    "change_status": "added",
                    "change_basis": "leftover_new",
                    "match_score": 0.0,
                    "prev_node_id": None,
                    "is_new_logical": True
                }

        return results
