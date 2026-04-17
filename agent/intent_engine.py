# agent/intent_engine.py
"""
DEPRECATED — Use agent.intent_parser + agent.intent_confirmer instead.

IntentEngine combined intent classification with registry selection in a single
pass. It has been superseded by a two-layer design:

  Layer 1   — IntentParser    (agent/intent_parser.py)   deterministic, zero latency
  Layer 1.5 — IntentConfirmer (agent/intent_confirmer.py) optional LLM correction

This file is retained for reference only. Do not import it in new code.
"""
from __future__ import annotations
import warnings as _warnings
_warnings.warn(
    "agent.intent_engine is deprecated and will be removed in a future release. "
    "Use agent.intent_parser.IntentParser and agent.intent_confirmer.IntentConfirmer instead.",
    DeprecationWarning,
    stacklevel=2,
)


from typing import Dict, Any, List, Optional
import re

from agent.query_registry import QueryRegistry, QueryEntry


# ---------------------------------------------------------------------------
# Tokenization & slot patterns
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[A-Za-z0-9\-_]+")
TAG_RE = re.compile(r"[A-Z]{2,5}-[A-Z]{1,5}-\d{1,5}")
NUMBER_RE = re.compile(r"\b\d+\b")
SYSTEM_RE = re.compile(r"\b[A-Z][A-Za-z0-9_\-]{2,40}\b")


# ---------------------------------------------------------------------------
# Ambiguity signal
# ---------------------------------------------------------------------------

class AmbiguityError(Exception):
    """
    Raised when multiple equally ranked queries remain after deterministic scoring.
    """

    def __init__(self, *, candidates: List[QueryEntry], message: str):
        super().__init__(message)
        self.candidates = candidates


# ---------------------------------------------------------------------------
# Intent Engine
# ---------------------------------------------------------------------------

class IntentEngine:
    """
    Deterministic intent extraction + registry-locked selection.

    Guarantees:
    - No mutation of QueryEntry
    - No silent guessing
    - Ambiguity only after scoring tie
    """

    def __init__(self, registry: QueryRegistry):
        self.registry = registry
        self._queries = registry.queries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_intent(self, question: str) -> Dict[str, Any]:
        q = question.strip()
        tokens = TOKEN_RE.findall(q.lower())

        return {
            "raw": q,
            "keywords": tokens,
            "intent_type": self._classify_intent(tokens),
            "slots": self._extract_slots(q),
        }

    def select_query(self, intent: Dict[str, Any]) -> QueryEntry:
        intent_type: str = intent["intent_type"]
        keywords = set(intent.get("keywords", []))
        slots = intent.get("slots", {})

        pool = self._filter_by_intent(intent_type)
        pool = self._filter_required_keywords(pool, keywords)
        pool = self._filter_exclusions(pool, keywords)
        pool = self._filter_by_slots(pool, slots)
        pool = self._filter_by_operation(pool, keywords)

        if not pool:
            raise RuntimeError(
                f"No verified query matches intent '{intent_type}'."
            )

        ranked = self._rank_candidates(pool, keywords, slots)

        top_score = ranked[0][0]
        best = [q for score, q in ranked if score == top_score]

        if len(best) == 1:
            return best[0]

        raise AmbiguityError(
            candidates=best,
            message="Multiple valid interpretations found. Please clarify."
        )

    # ------------------------------------------------------------------
    # Filtering phases
    # ------------------------------------------------------------------

    def _filter_by_intent(self, intent_type: str) -> List[QueryEntry]:
        return [q for q in self._queries if q["intent"] == intent_type]

    def _filter_required_keywords(
        self,
        pool: List[QueryEntry],
        keywords: set[str],
    ) -> List[QueryEntry]:
        result = []
        for q in pool:
            required = {k.lower() for k in q.get("required_keywords", [])}
            if required and not required.issubset(keywords):
                continue
            result.append(q)
        return result

    def _filter_exclusions(
        self,
        pool: List[QueryEntry],
        keywords: set[str],
    ) -> List[QueryEntry]:
        return [
            q for q in pool
            if not ({k.lower() for k in q.get("exclude_keywords", [])} & keywords)
        ]

    def _filter_by_slots(
        self,
        pool: List[QueryEntry],
        slots: Dict[str, Any],
    ) -> List[QueryEntry]:

        if "tag" in slots:
            tagged = [
                q for q in pool
                if q.get("target_entity") in {"equipment", "symbol"}
            ]
            return tagged or pool

        return pool

    def _filter_by_operation(
        self,
        pool: List[QueryEntry],
        keywords: set[str],
    ) -> List[QueryEntry]:

        op = self._detect_operation(keywords)
        if not op:
            return pool

        narrowed = [q for q in pool if q.get("operation") == op]
        return narrowed or pool

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_candidates(
        self,
        pool: List[QueryEntry],
        keywords: set[str],
        slots: Dict[str, Any],
    ) -> List[tuple[int, QueryEntry]]:

        scored: List[tuple[int, QueryEntry]] = []

        for q in pool:
            score = 0

            # boost keyword overlap
            boost = {k.lower() for k in q.get("boost_keywords", [])}
            score += len(boost & keywords) * 5

            # boost slot presence
            if "tag" in slots and q.get("target_entity"):
                score += 3

            # boost operation match
            op = self._detect_operation(keywords)
            if op and q.get("operation") == op:
                score += 4

            scored.append((score, q))

        # deterministic sort: score DESC, id ASC
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))

        return scored

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, tokens: List[str]) -> str:
        t = set(tokens)

        # inventory first (most specific)
        if t & {"how", "many", "count"} and t & {
            "pump", "tank", "valve", "instrument", "equipment"
        }:
            return "engineering_inventory"

        if t & {"valve", "valves"}:
            return "valve_placement"

        if t & {"instrument", "instruments", "pi", "ft", "lt"}:
            return "instrument_attachment"

        if t & {"line", "lines", "pipe", "pipes"}:
            return "line_attributes"

        if t & {"connected", "upstream", "downstream", "path", "between"}:
            return "connectivity_topology"

        if t & {"external", "boundary", "interface", "outside"}:
            return "external_interfaces"

        if t & {"duplicate", "identical", "redundant"}:
            return "redundancy_patterns"

        if t & {"missing", "orphan", "validate", "consistency"}:
            return "drawing_consistency"

        if t & {"isolated", "reachable", "reachability", "component",
                "island", "islands"}:
            return "isolation_reachability"

        if t & {"request", "requests", "review", "flagged", "flag",
                "anomaly", "pending"}:
            return "annotation_requests"

        if t & {"junction", "junctions", "joins", "adjacent",
                "adjacency", "t-junction", "tee"}:
            return "segment_junction_topology"

        return "unknown_intent"

    # ------------------------------------------------------------------
    # Slot extraction
    # ------------------------------------------------------------------

    def _extract_slots(self, question: str) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}

        if tag := TAG_RE.search(question):
            slots["tag"] = tag.group(0)

        if numbers := NUMBER_RE.findall(question):
            slots["numbers"] = numbers

        if systems := SYSTEM_RE.findall(question):
            slots["system_candidates"] = systems[:4]

        return slots

    def _detect_operation(self, keywords: set[str]) -> Optional[str]:
        if keywords & {"how", "many", "count", "number", "total", "quantity"}:
            return "count"
        if keywords & {"path", "between", "route"}:
            return "path"
        if keywords & {"list", "show", "which", "what"}:
            return "list"
        return None