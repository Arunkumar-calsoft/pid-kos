# agent/logical_plan_builder.py
"""
Logical Plan Builder — Layer 2

Responsibilities:
- Accept a parsed intent dict from IntentParser
- Filter the query registry down to matching candidates
- Rank deterministically (score DESC, id ASC tie-break)
- Return a single QueryEntry or raise AmbiguityError on score tie

Guarantees:
- Fully deterministic — scoring only, no LLM
- No mutation of QueryEntry objects
- No silent guessing — ambiguity always surfaces to caller
- Registry is read-only

Operation signal strength:
  Strong (how many / count / path): must narrow pool; if no registry entry
    matches, return [] so agent.py falls through to SchemaGenerator.
  Weak  (list / show / what): common words; do NOT force narrow — fall back
    to full pool so the user still gets results.
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

from agent.query_registry import QueryRegistry, QueryEntry


# ---------------------------------------------------------------------------
# Lightweight stemmer — handle common English suffixes so "ends" matches
# "end", "valves" matches "valve", etc.  No external dependency.
# ---------------------------------------------------------------------------

def _stem(word: str) -> str:
    """Strip common English suffixes for fuzzy keyword matching."""
    w = word.lower()
    # Longest unambiguous suffixes first
    for suffix in ("ations", "ments", "ness", "tion", "ment", "ing", "ies",
                   "ous", "ive", "ity", "ed", "ly", "er"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)]
    # Handle "-es" endings carefully to avoid "valves"→"valv" (was: strip "es" always)
    # Rule: strip just "s" unless the word ends in a sibilant cluster ("sses","zes","xes","ches","shes")
    # which needs the full "es" stripped.  Examples:
    #   "valves"  → strip "s"  → "valve"  ✓   (was "valv" ✗ with old logic)
    #   "pipes"   → strip "s"  → "pipe"   ✓   (was "pip"  ✗)
    #   "classes" → strip "es" → "class"  ✓
    #   "phases"  → strip "s"  → "phase"  ✓
    _SIBILANT_ES = ("sses", "zes", "xes", "ches", "shes")
    if len(w) > 4 and w.endswith("es"):
        if any(w.endswith(s) for s in _SIBILANT_ES):
            return w[:-2]   # "classes" → "class"
        return w[:-1]       # "valves"  → "valve", "pipes" → "pipe"
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


# ---------------------------------------------------------------------------
# Ambiguity signal
# ---------------------------------------------------------------------------

class AmbiguityError(Exception):
    """
    Raised when two or more candidates share the highest score after all
    deterministic filtering and ranking phases.
    Carries the tied candidates for the CLI to present to the user.
    """

    def __init__(self, *, candidates: List[QueryEntry], message: str) -> None:
        super().__init__(message)
        self.candidates = candidates


# ---------------------------------------------------------------------------
# Logical Plan Builder
# ---------------------------------------------------------------------------

class LogicalPlanBuilder:
    """
    Converts a parsed intent into a single verified QueryEntry.

    Pipeline (all phases deterministic):
        1. Filter by intent type
        2. Filter by required keywords
        3. Filter by exclusion keywords
        4. Filter by slot presence
        5. Filter by detected operation
        6. Rank by boost keywords + slot bonus + operation bonus
        7. Return top-1 or raise AmbiguityError on tie
    """

    def __init__(self, registry: QueryRegistry) -> None:
        self._queries = registry.queries

    def build(self, intent: Dict[str, Any]) -> QueryEntry:
        intent_type: str      = intent["intent_type"]
        keywords:    set[str] = set(intent.get("keywords", []))
        slots:       Dict     = intent.get("slots", {})

        pool = self._queries
        pool = self._filter_by_intent(pool, intent_type)
        pool = self._filter_required_keywords(pool, keywords)
        pool = self._filter_exclusions(pool, keywords)
        pool = self._filter_by_slots(pool, slots)
        pool = self._filter_by_operation(pool, keywords)

        if not pool:
            raise RuntimeError(
                f"No verified query matches intent '{intent_type}'. "
                "Check registry entries or refine the question."
            )

        ranked    = self._rank_candidates(pool, keywords, slots)
        top_score = ranked[0][0]
        best      = [q for score, q in ranked if score == top_score]

        if len(best) == 1:
            return best[0]

        # Zero-score tie means NO keyword matched any candidate — none of
        # these registry entries are actually relevant.  Fall through to
        # SchemaGenerator which has richer keyword-branching logic.
        if top_score == 0:
            raise RuntimeError(
                f"No confident registry match for intent '{intent_type}' "
                f"(all {len(best)} candidates scored 0). "
                "Falling through to schema generation."
            )

        raise AmbiguityError(
            candidates=best,
            message=(
                "Multiple valid interpretations found. "
                "Please clarify which query you intended."
            ),
        )

    # ------------------------------------------------------------------
    # Filter phases
    # ------------------------------------------------------------------

    def _filter_by_intent(
        self, pool: List[QueryEntry], intent_type: str
    ) -> List[QueryEntry]:
        return [q for q in pool if q["intent"] == intent_type]

    def _filter_required_keywords(
        self, pool: List[QueryEntry], keywords: set[str]
    ) -> List[QueryEntry]:
        # Use stemmed matching so "pumps" matches required "pump", "valves"→"valve", etc.
        stemmed_keywords = {_stem(k) for k in keywords}
        result = []
        for q in pool:
            required = {k.lower() for k in q.get("required_keywords", [])}
            if required:
                required_stemmed = {_stem(k) for k in required}
                if not required_stemmed.issubset(stemmed_keywords):
                    continue
            result.append(q)
        return result

    def _filter_exclusions(
        self, pool: List[QueryEntry], keywords: set[str]
    ) -> List[QueryEntry]:
        return [
            q for q in pool
            if not (
                {k.lower() for k in q.get("exclude_keywords", [])} & keywords
            )
        ]

    def _filter_by_slots(
        self, pool: List[QueryEntry], slots: Dict[str, Any]
    ) -> List[QueryEntry]:
        if "tag" in slots:
            tagged = [
                q for q in pool
                if q.get("target_entity") in {"equipment", "symbol"}
            ]
            return tagged or pool
        return pool

    def _filter_by_operation(
        self, pool: List[QueryEntry], keywords: set[str]
    ) -> List[QueryEntry]:
        op, strong = self._detect_operation(keywords)
        if not op:
            return pool
        narrowed = [q for q in pool if q.get("operation") == op]
        if narrowed:
            return narrowed
        # Strong signal with no matching registry entry → return [] so agent.py
        # builds a synthetic QueryEntry and SchemaGenerator handles it.
        if strong:
            return []
        # Weak signal → full pool (avoid losing valid candidates)
        return pool

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _rank_candidates(
        self,
        pool:     List[QueryEntry],
        keywords: set[str],
        slots:    Dict[str, Any],
    ) -> List[tuple[int, QueryEntry]]:
        scored: List[tuple[int, QueryEntry]] = []
        op, _ = self._detect_operation(keywords)
        stemmed_kw = {_stem(k) for k in keywords}
        for q in pool:
            score = 0
            boost = {k.lower() for k in q.get("boost_keywords", [])}
            # Exact match scores higher; stemmed match still counts
            exact_hits   = len(boost & keywords)
            stemmed_boost = {_stem(b) for b in boost}
            stem_hits    = len(stemmed_boost & stemmed_kw) - exact_hits
            score += exact_hits * 5 + max(stem_hits, 0) * 3
            if "tag" in slots and q.get("target_entity"):
                score += 3
            if op and q.get("operation") == op:
                score += 4
            scored.append((score, q))
        # Deterministic: score DESC, id ASC as tie-break
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return scored

    # ------------------------------------------------------------------
    # Operation detection
    # ------------------------------------------------------------------

    def _detect_operation(self, keywords: set[str]) -> tuple[Optional[str], bool]:
        """
        Returns (operation, is_strong_signal).
        Strong signals force schema generation when no registry entry matches.
        Weak signals fall back to full pool.

        NOTE: "count" is always strong so the SchemaGenerator count branch
        is triggered even when no registry .cypher file covers this operation.
        The intent_parser already routed to the right intent (line_attributes,
        valve_placement, etc.) so the SchemaGenerator will use the correct
        node label — we just need to pass op="count" through.
        """
        if keywords & {"how", "many", "count", "total", "quantity"}:
            return "count", True      # strong — unambiguous count request
        if keywords & {"path", "between", "route"}:
            return "path", True       # strong — structurally distinct query
        if keywords & {"number"}:
            return "count", False     # weak — "number" can appear in tag names
        if keywords & {"list", "show", "which", "what", "all"}:
            return "list", False      # weak — very common words
        return None, False