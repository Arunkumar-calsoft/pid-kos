# agent/intent_parser.py
"""
Intent Parser — Layer 1

Responsibilities:
- Tokenize and normalize the raw user question
- Classify intent type from keyword signals
- Expand compound words (e.g. "pipesegments" → pipe + segment)
- Extract entity slots (equipment tags, numbers, system candidates)

Intent routing for count queries is SUBJECT-AWARE:
  "how many valves"        → valve_placement      (Equipment WHERE type CONTAINS 'valve')
  "how many pipe segments" → line_attributes       (LogicalPipeSegment)
  "how many instruments"   → instrument_attachment (Annotation)
  "how many arrows"        → engineering_inventory  (Node WHERE label='arrow')
  "how many equipment"     → engineering_inventory (Equipment — generic)

This prevents "how many pipesegments" from mistakenly routing to
engineering_inventory (which only queries the Equipment node label).

Guarantees:
- Pure extraction: no registry access, no query selection
- Stateless and deterministic
- Always returns a complete intent dict with all required keys

Output schema (all keys always present):
{
    "raw":           str,
    "keywords":      List[str],
    "intent_type":   str,
    "slots": {
        "tag":               str       (optional),
        "numbers":           List[str] (optional),
        "system_candidates": List[str] (optional),
    },
    "pid_id":        str,   # default "UNKNOWN"
    "graph_version": str,   # default "latest"
}
"""
from __future__ import annotations

import re
from typing import Dict, Any, List, Set, Optional

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

TOKEN_RE  = re.compile(r"[A-Za-z0-9\-_]+")
# Equipment tag patterns — covers both XX-YYY-NNN (PSV-A-123) and XX-NNN (FV-001)
TAG_RE    = re.compile(r"[A-Z]{2,5}-(?:[A-Z]{1,5}-)?\d{1,5}")
# Inline node ID references (tank67, valve12, connector5, tank 70, inlet/outlet13, instrumentation108)
NODE_ID_RE = re.compile(r"\b(?:tank|valve|connector|arrow|instrument(?:ation)?|general|inlet/outlet)\s*\d+\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+\b")
SYSTEM_RE = re.compile(r"\b[A-Z][A-Za-z0-9_\-]{2,40}\b")

# ---------------------------------------------------------------------------
# Compound word expansions
# ---------------------------------------------------------------------------

_COMPOUND_MAP: Dict[str, List[str]] = {
    # pipe segment variants
    "pipesegment":          ["pipe", "segment"],
    "pipesegments":         ["pipe", "segment", "segments"],
    "pipelinesegment":      ["pipe", "line", "segment"],
    "pipelinesegments":     ["pipe", "line", "segment", "segments"],
    "logicalpipe":          ["logical", "pipe", "segment"],
    "logicalpipesegment":   ["logical", "pipe", "segment"],
    "logicalpipesegments":  ["logical", "pipe", "segment", "segments"],
    "piperun":              ["pipe", "run", "segment"],
    "piperuns":             ["pipe", "run", "segment", "segments"],
    "pipework":             ["pipe", "segment"],
    # flow direction variants
    "flowdirection":        ["flow", "direction"],
    "flowdirections":       ["flow", "direction"],
    # equipment variants
    "equipmenttype":        ["equipment", "type"],
    # annotation / instrument variants
    "instrumentation":      ["instrument"],
    "instrumentations":     ["instrument", "instruments"],
    "annotations":          ["annotation"],
    # other
    "drawingconsistency":   ["drawing", "consistency"],
    "valveplacement":       ["valve", "placement"],
    "connectivity":         ["connected", "connection"],
    "redundancy":           ["redundant", "duplicate"],
    "disconnectedsegments": ["disconnected", "segment", "segments"],
    "isolatedsegments":     ["isolated", "segment", "segments"],
    "deadleg":              ["dead", "dangling", "end"],
    "dead-leg":             ["dead", "dangling", "end"],
    "dead-end":             ["dead", "dangling", "end"],
    "deadlegs":             ["dead", "dangling", "end"],
    "danglingend":          ["dangling", "end"],
    "danglingends":         ["dangling", "end", "ends"],
    "openend":              ["dangling", "end", "blind"],
    "openends":             ["dangling", "end", "ends", "blind"],
    "tjunction":            ["junction", "tee", "branch"],
    "t-junction":           ["junction", "tee", "branch"],
    "tjunctions":           ["junction", "tee", "branch"],
    # ── Safety equipment compound forms ────────────────────────────────────
    "checkvalve":           ["check", "valve"],
    "checkvalves":          ["check", "valve", "valves"],
    "check-valve":          ["check", "valve"],
    "check-valves":         ["check", "valve", "valves"],
    "reliefvalve":          ["relief", "valve"],
    "reliefvalves":         ["relief", "valve", "valves"],
    "relief-valve":         ["relief", "valve"],
    "safetyvalve":          ["safety", "valve"],
    "safetyvalves":         ["safety", "valve", "valves"],
    "safety-valve":         ["safety", "valve"],
    "suctionstrainer":      ["suction", "strainer"],
    "suction-strainer":     ["suction", "strainer"],
    "inlineequipment":      ["inline", "equipment"],
    "inline-equipment":     ["inline", "equipment"],
    "reverseflow":          ["reverse", "flow"],
    "reverse-flow":         ["reverse", "flow"],
    # "lps-to-lps" is a compound form for the LPS adjacency graph.
    "lps-to-lps":           ["lps", "adjacency"],
    # ── Severity / confidence hyphenated forms ─────────────────────────────
    # TOKEN_RE includes hyphens so "high-severity" is ONE token; expand it.
    "high-severity":        ["high", "severity"],
    "medium-severity":      ["medium", "severity"],
    "low-severity":         ["low", "severity"],
    "low-confidence":       ["low", "confidence"],
    "low_confidence":       ["low", "confidence"],
    # ── Phase4 / annotation type names ─────────────────────────────────────
    # These appear verbatim in engineer questions. Expand to trigger words
    # that are already in _ANNOTATION_TRIAGE_WORDS or _FLOW_COVERAGE_WORDS.
    "phase4_hint":                          ["phase4", "hint"],
    "phase4-hint":                          ["phase4", "hint"],
    "propagation_blocked":                  ["propagation", "blocked"],
    "propagation-blocked":                  ["propagation", "blocked"],
    "terminate_propagation":                ["terminate", "phase4"],
    "requires_fallback_rule_or_hitl":       ["fallback", "hitl", "requires"],
    "use_as_traversal_index":               ["traversal", "traversal_index"],
    "lps_low_confidence_evidence":          ["low", "confidence", "evidence", "lps"],
    "pipe_segment_no_logical_mapping":      ["pipe", "segment", "missing", "logical"],
    "structural_pattern_frequency":         ["structural", "pattern", "frequency"],
    "structural_pattern_rarity":            ["structural", "pattern", "rarity"],
    "rare_motif_local":                     ["rare", "motif", "rarity"],
    "structural_high_degree":               ["structural", "high", "degree"],
    "structural_t_junction":                ["structural", "junction", "tee"],
    "structural_branch":                    ["structural", "branch", "junction"],
    "large_manifold_node":                  ["manifold", "large", "degree"],
    "pipe_segment_cycle_member":            ["pipe", "segment", "cycle", "loop"],
    "orphan_node":                          ["orphan", "node"],
    "endpoint_collision":                   ["endpoint", "collision"],
    "dead_end_pipe_segment":                ["dead", "dangling", "pipe", "segment"],
    "ps_unreachable_from_evidence":         ["unreachable", "pipe", "segment", "evidence"],
    # Fix 5: ESV/KAV category hyphenated forms
    "esv-category":     ["esv", "category"],
    "kav-category":     ["kav", "category"],
    "high-degree":      ["high", "degree"],
    # hitl_severity as a compound token
    "hitl_severity":    ["hitl", "severity"],
    "hitl-severity":    ["hitl", "severity"],
    "highest-degree":   ["degree", "high"],     # "highest-degree nodes" → connectivity_topology
    # Fix E: geometry_hash is a PipeSegment property → line_attributes
    "geometry_hash":    ["geometry", "hash", "segment", "pipe"],
    "geometry-hash":    ["geometry", "hash", "segment", "pipe"],
}

# Root words detected inside long compound tokens (>9 chars)
_KNOWN_ROOTS = (
    "pipe", "valve", "segment", "instrument", "equipment",
    "flow", "arrow", "annotation", "connect", "external",
    "boundary", "redundan", "duplicat", "consist", "orphan",
    "missing", "direction", "logical", "geometry",
    "check", "relief", "safety", "strainer", "suction", "inline",
    "adjacent", "forward", "reverse",
)

# ---------------------------------------------------------------------------
# Subject-domain keyword sets — used for count routing
# ---------------------------------------------------------------------------

# Pipe / segment subjects → line_attributes (LogicalPipeSegment)
_PIPE_SUBJECTS: Set[str] = {
    "pipe", "pipes", "segment", "segments",
    "pipesegment", "pipesegments",
    "lps", "logical",
    "piperun", "piperuns", "pipework",
    "run", "runs",
    "line", "lines",
}

# Valve subjects → valve_placement
_VALVE_SUBJECTS: Set[str] = {
    "valve", "valves",
    "cv", "pv", "hv", "sdv", "psv", "prv", "bv",
    "gate", "gates", "globe", "ball", "butterfly", "check",
}

# Instrument / annotation subjects → instrument_attachment (Annotation)
_INSTRUMENT_SUBJECTS: Set[str] = {
    "instrument", "instruments", "instrumentation",
    "tag", "tags", "label", "labels",
    "indicator", "transmitter", "controller", "sensor",
    "pi", "ft", "lt", "pt", "fit", "lic", "pic", "tic",
}

# Arrow subjects → flow_direction (Arrow)
_ARROW_SUBJECTS: Set[str] = {
    "arrow", "arrows",
    "flowdirection", "flowdirections",
}

# Tank/pump-like subjects — used by engineering_correctness routing
# "pump" is a common field synonym for tank nodes (no pump label exists in graph)
_TANK_LIKE: Set[str] = {
    "tank", "tanks", "vessel", "vessels",
    "pump", "pumps", "compressor", "compressors",
    "heater", "heaters", "exchanger", "exchangers",
    "equipment",
}

# Generic equipment subjects → engineering_inventory (Equipment)
_EQUIPMENT_SUBJECTS: Set[str] = {
    "equipment",
    "pump", "pumps",
    "tank", "tanks",
    "vessel", "vessels",
    "exchanger", "exchangers",
    "compressor", "compressors",
    "turbine", "turbines",
    "skid", "skids",
    "item", "items",
    "strainer", "strainers",
    "inline",
    # Drawing-symbol inventory words — map to engineering_inventory (show all symbols/connectors)
    "symbol", "symbols",
    "connector", "connectors",
}


# ---------------------------------------------------------------------------
# Cross-domain signal sets — pairs of domains present in one question
# ---------------------------------------------------------------------------

# Any of these trigger cross_domain routing when combined with a different domain
_CROSS_DOMAIN_ANCHORS: Dict[str, Set[str]] = {
    "valve":      _VALVE_SUBJECTS,
    "instrument": _INSTRUMENT_SUBJECTS,
    "pipe":       _PIPE_SUBJECTS,
    "equipment":  _EQUIPMENT_SUBJECTS,
    "arrow":      _ARROW_SUBJECTS,
    "flow":       {"flow", "direction", "upstream", "downstream", "seeded", "propagated", "unknown"},
}

# Cross-domain questions explicitly join/filter across domains.
# Simple flow-on-pipe or downstream-of-valve questions (single concern) do NOT
# have these words and should stay on their dedicated generators.
_CROSS_DOMAIN_LINK_WORDS: Set[str] = {
    "both", "and", "with", "without", "containing", "that",
    "whose", "where", "combining", "across", "having",
}

def _count_domains(t: Set[str]) -> int:
    """Count how many distinct domains have a keyword hit."""
    return sum(1 for s in _CROSS_DOMAIN_ANCHORS.values() if t & s)


# ---------------------------------------------------------------------------
# Annotation triage / metadata — hitl_severity, ESV, KAV, priority
# These questions are never instrument queries; route to cross_domain so the
# GroundedGenerator gets the full annotation schema.
# ---------------------------------------------------------------------------

_ANNOTATION_TRIAGE_WORDS: Set[str] = {
    "esv", "kav",                           # annotation taxonomy families
    "hitl", "triage",                       # triage metadata
    "canary", "audience",                   # annotation metadata fields
    "priority",                             # "high priority issues"
    "attention",                            # "which valves need attention?"
    "review",                               # "what needs human review?"
    # NOTE: "severity" and "critical" intentionally NOT here —
    # "show all high-severity annotations" → annotation_requests (simple filtered list)
    # "critical severity violations" → engineering_correctness (uses required_keywords filter)
    # BUG-2: equipment semantics annotations routed to cross_domain
    "semantics",                            # "equipment semantics annotations"
    # BUG-4: phase4_hint-specific queries
    "phase4",                               # "phase4_hint values"
    "terminate",                            # "terminate_propagation" (phase4 directive)
    "fallback",                             # "requires_fallback_rule_or_hitl"
    "traversal_index",                      # "use_as_traversal_index"
    # BUG-5: temporal annotation metadata queries
    "first_seen", "recent", "recently",     # "most recently created annotations"
    "pipeline",                             # "grouped by source pipeline phase"
    "intent",                               # "annotations grouped by intent"
}

# ---------------------------------------------------------------------------
# Isolation / reachability — component_id-based separation from main network
# Distinct from drawing_consistency: these are topology queries, not defect checks.
# ---------------------------------------------------------------------------

_ISOLATION_WORDS: Set[str] = {
    "isolated", "component", "components",
    "island", "islands",
    "reachable", "reachability",
    "reach", "reaches", "unreachable",
    "disconnected",
}

# ---------------------------------------------------------------------------
# Flow coverage — analysis completeness query, not a drawing defect check
# "how complete is the flow analysis?" / "what percentage of pipes have flow?"
# These questions are about the system's analysis reach, not drawing quality.
# Must fire before flow_direction so "coverage" and "gaps" don't get absorbed
# into a generic flow direction query.
# ---------------------------------------------------------------------------

_FLOW_COVERAGE_WORDS: Set[str] = {
    "coverage", "covered", "resolved", "unresolved",
    "complete", "completeness",
    "proportion", "percentage", "percent",
    "gaps",                                 # "flow direction gaps" → flow_coverage
    # BUG-3: low-confidence evidence queries belong to flow_coverage
    "lps_low_confidence_evidence",          # annotation type name
    # BUG-6: propagation_blocked is an LPS flow coverage concern
    "blocked",                              # "propagation_blocked=true"
}

# ---------------------------------------------------------------------------
# Engineering correctness — topology-based P&ID conformance checks.
# Distinct from drawing_consistency (pre-computed defects) and
# isolation_reachability (graph component separation).
# These questions ask whether the drawing follows engineering rules:
#   - every tank has instruments
#   - every pump is isolatable
#   - control valves have bypass paths
# ---------------------------------------------------------------------------

_ENGINEERING_CORRECTNESS_WORDS: Set[str] = {
    "isolatable", "isolable",                 # isolation capability
    "bypassed", "bypass",                     # bypass existence
    "instrumented", "unmonitored",            # instrument coverage
    "correctness", "correct",                 # explicit correctness check
    "engineering",                            # "engineering check/review"
    "compliant", "compliance",                # conformance language
    "violation", "violations",                # explicit rule violations
    "rule", "rules",                          # "engineering rules"
    "protection",                             # "reverse flow protection"
    "strainer",                               # "missing suction strainer"
    "suction",                                # "suction strainer check"
}


# ---------------------------------------------------------------------------
# PID reference extraction — inline question override
# ---------------------------------------------------------------------------

_PID_RE = re.compile(
    r'\b(?:PID[_\-\s]?(\d+)|drawing[_\-\s]?(\d+)|diagram[_\-\s]?(\d+))\b',
    re.IGNORECASE,
)


def _extract_pid_from_question(question: str) -> Optional[str]:
    """
    Return a PID id (e.g. 'PID_2') if the question explicitly references one.
    Returns None if no reference found — caller uses the session default.

    Recognises:
        "on PID 2", "PID_2", "PID-2"
        "on drawing 2", "drawing_2"
        "on diagram 3"
    """
    m = _PID_RE.search(question)
    if m:
        num = m.group(1) or m.group(2) or m.group(3)
        if num:
            return f"PID_{num}"
    return None


class IntentParser:
    """
    Parses a raw user question into a structured intent dictionary.
    No registry access. No side effects.
    """

    def parse(self, question: str, pid_id: str = "UNKNOWN") -> Dict[str, Any]:
        q        = question.strip()
        tokens   = TOKEN_RE.findall(q.lower())
        expanded = self._expand_all(set(tokens))

        # Mark when a specific node ID or equipment tag is referenced in the question.
        # This lets _classify_intent steer "what valves are connected to tank67?"
        # to connectivity_topology instead of valve_placement.
        if NODE_ID_RE.search(q) or TAG_RE.search(q):
            expanded.add("__node_id_present")

        # Inline PID reference in the question overrides the session default.
        # e.g. "how many valves on PID_3?" works even if active drawing is PID_2.
        extracted_pid = _extract_pid_from_question(q)

        return {
            "raw":           q,
            "keywords":      list(expanded),
            "intent_type":   self._classify_intent(expanded),
            "slots":         self._extract_slots(q),
            "pid_id":        extracted_pid or pid_id,
            "graph_version": "latest",
        }

    # ------------------------------------------------------------------
    # Compound word expansion
    # ------------------------------------------------------------------

    def _expand_all(self, tokens: Set[str]) -> Set[str]:
        """Return tokens union with any compound-word expansions."""
        expanded = set(tokens)
        for token in tokens:
            if token in _COMPOUND_MAP:
                expanded.update(_COMPOUND_MAP[token])
            elif len(token) > 9:
                for root in _KNOWN_ROOTS:
                    if root in token:
                        expanded.add(root)
        return expanded

    # ------------------------------------------------------------------
    # Intent classification — subject-aware, deterministic
    # ------------------------------------------------------------------

    # Quality/status words that ALWAYS override subject-domain routing.
    # "how many disconnected segments" must go to drawing_consistency,
    # not line_attributes, because the generator there knows how to filter
    # by status/connectivity rather than doing a raw count.
    _QUALITY_WORDS: Set[str] = {
        # missing / unattached
        "missing", "orphan", "orphaned", "unattached", "floating",
        # validation / consistency
        "validate", "validation", "consistency", "inconsistent",
        "consistent", "structurally", "structural",
        # structural problems
        "incomplete", "broken",
        # dangling ends / dead legs
        "dangling", "dead", "deadleg", "terminus", "termination",
        "stub", "blind", "end-cap", "endcap",
        # loops / cycles
        "loop", "loops", "cycle", "cycles",
        # structural topology patterns (query by name = structural inventory mode)
        "manifold",                         # "large manifold nodes"
        "high-degree", "high_degree",       # "high-degree nodes"
        "collision",                        # "endpoint collision nodes"
        "endpoint",                         # "endpoint collision"
        # general quality — include plural forms
        "quality", "issue", "issues", "error", "problem", "problems",
        "bad", "failed", "fail", "wrong",
        "defect", "defects",                # "are there any drawing defects?"
        "report",                           # "drawing quality report" — triggers drawing_consistency
                                            # unless "annotation" also present (→ annotation_requests)
    }

    # Connectivity-quality words trigger drawing_consistency when paired
    # with a boolean context ("are all pipes connected?", "is everything
    # connected?", "verify connectivity").  Without boolean context they
    # fall through to connectivity_topology (directional path queries).
    _CONNECTIVITY_QUALITY_WORDS: Set[str] = {
        "connected", "connection", "connections", "connectivity",
    }

    _BOOLEAN_STARTERS: Set[str] = {
        "all", "every", "everything", "any", "are", "is", "verify",
        "check", "confirm", "ensure", "fully", "properly",
    }

    def _classify_intent(self, t: Set[str]) -> str:
        # ── 0. Annotation triage / metadata → cross_domain ───────────────
        # ESV, KAV, severity, priority, review — engineer-facing triage words.
        # Must fire before _QUALITY_WORDS so "critical issues" / "high priority"
        # reach GroundedGenerator with full annotation schema, not drawing_consistency.
        # Exception: "phase4" combined with LPS/pipe/flow-state context is a
        # flow_coverage query (e.g. "how many LPS have phase4_hint X?"), not triage.
        _triage_words = _ANNOTATION_TRIAGE_WORDS - {"phase4"}
        if t & _triage_words:
            return "cross_domain"
        if "phase4" in t and not (t & _PIPE_SUBJECTS and t & {"flow", "state", "direction", "hint", "lps"}):
            return "cross_domain"

        # ── 0.5. Severity-filtered annotation list → annotation_requests ──────
        # "show HIGH-severity annotations", "show all CRITICAL annotations",
        # "severity breakdown" — engineer wants a filtered list, not triage.
        # Must come AFTER step 0 so ESV/KAV/HITL/review context (already tested)
        # still routes to cross_domain.
        # Guard: violation context ("violations","rule","engineering") falls through
        # to engineering_correctness (step 1.5) instead.
        _violation_ctx = bool(t & {"violation", "violations", "rule", "rules"})
        if t & {"severity", "critical", "medium", "level"} and not _violation_ctx:
            return "annotation_requests"


        # MUST fire before _QUALITY_WORDS because "missing flow direction" contains
        # "missing" which is in _QUALITY_WORDS — but it is an analysis coverage
        # question, not a drawing defect question.
        #
        # Rule: pipe/line/lps subject + (coverage word  OR  missing/unresolved +
        #       explicit "direction" anchor).
        # "which pipe lines are missing flow direction?" → flow_coverage
        # "show me segments with unknown flow"          → flow_direction (no "direction")
        # "how complete is the flow analysis?"          → flow_coverage
        _flow_subj = bool(t & _PIPE_SUBJECTS or t & {"lps", "flow", "lines"})
        _coverage_explicit   = bool(t & _FLOW_COVERAGE_WORDS)
        # "don't have a flow direction" → "don" + "direction" in tokens
        _missing_direction   = bool(
            t & {"missing", "unresolved", "no", "not", "don", "without", "lacking"}
            and "direction" in t
        )
        # "no flow evidence via LPS" / "pipe segments with no evidence" → flow_coverage
        _evidence_gap = bool(
            "evidence" in t
            and t & {"missing", "no", "without", "unreachable", "gap", "gaps"}
            and _flow_subj
        )
        # "how many LPS have a direction observation annotation?" → flow_coverage
        # direction + annotation/observation on LPS = annotation-based coverage query
        _direction_annotation = bool(
            "direction" in t
            and t & {"observation", "annotation", "annotations"}
            and _flow_subj
        )
        # BUG-3: "low-confidence LPS", "low confidence evidence" → flow_coverage
        # These query Annotation.type='lps_low_confidence_evidence', not raw flow data.
        _low_confidence_lps = bool(
            t & {"low", "lps_low_confidence_evidence"}
            and t & {"confidence", "uncertain"}
            and _flow_subj
        )
        # BUG-6: "propagation_blocked=true" → flow_coverage (LPS coverage concern)
        _propagation_blocked = bool(
            t & {"blocked", "propagation_blocked"}
            and _flow_subj
        )
        # Fix 5: "resolved" is in _FLOW_COVERAGE_WORDS but "valves with resolved flow
        # direction" is a Node-level flow query → flow_direction, not flow_coverage.
        # Suppress flow_coverage when a specific equipment subject is present.
        # Also suppress for "SYMBOL nodes" — structural_type='SYMBOL' flow queries
        # are Node-level, not LPS coverage queries.
        _has_equip_subject = bool(
            t & _VALVE_SUBJECTS
            or t & _INSTRUMENT_SUBJECTS
            or t & _TANK_LIKE
            or t & {"symbol", "symbols"}    # "SYMBOL nodes with resolved flow direction"
        )
        if _flow_subj and not _has_equip_subject and (
            _coverage_explicit or _missing_direction
            or _evidence_gap or _direction_annotation
            or _low_confidence_lps or _propagation_blocked
        ):
            return "flow_coverage"

        # ── 1.5. Engineering correctness — topology conformance checks ──────
        # Must fire before _QUALITY_WORDS because "do all tanks have instruments?"
        # contains no quality words but IS an engineering correctness question.
        # Also handles explicit words: isolatable, bypassed, instrumented.
        # Three triggers:
        #   A) explicit engineering correctness word (isolatable, bypassed, …)
        #   B) "do all"/"does every"/"are all" + equipment + known check word
        #   C) equipment subject + "correct"/"compliant"/"engineering"
        _has_eng_word  = bool(t & _ENGINEERING_CORRECTNESS_WORDS)
        _has_tank_like = bool(t & _TANK_LIKE)
        _has_all_every = bool(t & {"all", "every", "each"})
        _has_negation  = bool(t & {"no", "without", "missing", "lack", "lacking",
                                   "none", "not", "never"})
        _has_coverage_word = bool(t & {"have", "has", "with", "without", "no"})

        if _has_eng_word:
            return "engineering_correctness"

        # "do all tanks have instruments?"  "does every tank have a valve?"
        if _has_tank_like and _has_all_every and _has_coverage_word:
            if t & _INSTRUMENT_SUBJECTS or t & {"valve", "valves", "isolation",
                                                 "isolat", "bypass"}:
                return "engineering_correctness"

        # "which tanks have no instrumentation?"  "tanks without instruments"
        # Tank subject + negation + instrument/valve subject → correctness check,
        # not a plain instrument_attachment query.
        if _has_tank_like and _has_negation and (
            t & _INSTRUMENT_SUBJECTS or t & _VALVE_SUBJECTS
        ):
            return "engineering_correctness"

        # "which tanks are unmonitored?" "unmonitored vessels"
        # Already caught by _ENGINEERING_CORRECTNESS_WORDS, but belt-and-braces:
        if _has_tank_like and t & {"unmonitored", "instrumented", "monitored",
                                   "uninstrumented"}:
            return "engineering_correctness"

        # ── 2. Drawing quality → drawing_consistency ──────────────────────
        # Orphans, dangling ends, consistency, loops, general quality words.
        #
        # Exception: if a quality word appears alongside a specific equipment
        # domain AND a link word, the question is cross-domain — not a standalone
        # defect check.  e.g. "valves with flow problems" should reach
        # cross_domain/GroundedGenerator, not the drawing_consistency generator
        # which only knows how to query the pre-computed defect annotation set.
        if t & self._QUALITY_WORDS:
            # BUG-1: "dangling" + instrument/valve/inline label → AnnotationRequest
            # DANGLING_INLINE lives on AnnotationRequest, not Annotation.
            # "inline" explicitly signals the AnnotationRequest anomaly type.
            # Do NOT trigger for bare "dangling"+"nodes" (dead-end pipe segment = Annotation).
            if "dangling" in t and (
                t & _INSTRUMENT_SUBJECTS
                or t & _VALVE_SUBJECTS
                or "inline" in t
            ):
                return "annotation_requests"
            # "orphan node annotation requests" → AnnotationRequest
            if t & {"orphan", "orphaned"} and t & {"request", "requests"}:
                return "annotation_requests"
            # Fix 4: "drawing quality report" → annotation_requests
            if t & {"report"} and t & {"drawing", "quality", "issues", "defects"}:
                return "annotation_requests"
            # Fix 5: "how many issues involve instruments?" → annotation_requests
            if t & {"issue", "issues"} and t & _INSTRUMENT_SUBJECTS and t & {"how", "many", "count"}:
                return "annotation_requests"
            if t & {"issue", "issues"} and t & _VALVE_SUBJECTS and t & {"how", "many", "count"}:
                return "annotation_requests"
            # Fix A: "show all structural branch/manifold/high-degree/tee/junction nodes"
            # These are structural inventory list queries → cross_domain so
            # GroundedGenerator builds the Annotation.type query without registry AmbiguityError.
            _struct_type_words = {"branch", "branches", "manifold",
                                  "high-degree", "high_degree", "tee", "tees",
                                  "junction", "junctions", "t-junction", "t-junctions"}
            _list_intent_q = bool(t & {"show", "list", "all", "display", "give"})
            _has_count_q   = bool(t & {"how", "many", "count", "total", "quantity"})
            if t & _struct_type_words and _list_intent_q and not _has_count_q:
                return "cross_domain"
            # Fix D: "isolated valves" → drawing_consistency (degree-0 = orphan check).
            # Only for isolated/orphaned — NOT for reach-based queries (those go to isolation_reachability).
            if t & _VALVE_SUBJECTS and t & {"isolated", "orphan", "orphaned"} and not t & {"reach", "reachable"}:
                return "drawing_consistency"
            _equip_domains = (
                bool(t & _VALVE_SUBJECTS)
                or bool(t & _INSTRUMENT_SUBJECTS)
                or bool(t & _EQUIPMENT_SUBJECTS)
            )
            if _equip_domains and (t & _CROSS_DOMAIN_LINK_WORDS):
                return "cross_domain"
            # Quality + isolation context = cross-domain
            if t & _ISOLATION_WORDS:
                return "cross_domain"
            # "structural pattern frequency/rarity" annotations → redundancy_patterns.
            # Must guard BEFORE falling to drawing_consistency so the rarity scorer
            # and GroundedGenerator see the correct intent bucket.
            if t & {"frequency", "rarity", "rare", "motif", "dominant", "architecturally"}:
                return "redundancy_patterns"
            return "drawing_consistency"

        # ── 2.5. "components" disambiguation ─────────────────────────────
        # In P&ID engineering "components" = equipment/parts (engineering_inventory),
        # NOT graph-connected-components. Only route to isolation_reachability when
        # explicit graph-theory isolation context words are also present.
        if t & {"component", "components"}:
            _has_iso = bool(t & {
                "isolated", "disconnected", "island", "islands",
                "reachable", "reachability", "reach", "reaches", "unreachable",
                "connected",  # "show connected components" = topology
            })
            if not _has_iso and t & _PIPE_SUBJECTS:
                # "segments in main component" = PipeSegment.component_id query
                return "line_attributes"
            if not _has_iso:
                # "show all components" without pipe/topology context = equipment
                return "engineering_inventory"
            # has_iso → fall through to step 3 (isolation_reachability)

        # ── 3. Isolation / reachability → isolation_reachability ──────────
        # "isolated segments", "disconnected nodes", "can flow reach X?"
        # Fix D: "isolated valves" → drawing_consistency (degree-0 = orphan check,
        # not component-id isolation). BUT: "can flow reach every valve?" /
        # "which valves cannot reach any inlet?" → isolation_reachability.
        # Only divert to drawing_consistency for isolated/orphaned — NOT for reach queries.
        if t & _ISOLATION_WORDS:
            _reach_words = {"reach", "reaches", "reachable", "reachability", "unreachable"}
            _orphan_words = {"isolated", "orphan", "orphaned"}
            if (t & _VALVE_SUBJECTS or t & _INSTRUMENT_SUBJECTS) and t & _orphan_words and not t & _reach_words:
                return "drawing_consistency"
            return "isolation_reachability"

        # ── 4. Flow-on-pipe disambiguation ────────────────────────────────
        # "segments with unknown flow" / "pipes without a flow direction" →
        # flow_direction. Only fires when there is NO equipment domain also present.
        # Fix 4&7: do NOT fire for count queries about LPS states
        # ("how many LPS have SEEDED/UNKNOWN flow state?" → line_attributes).
        # Also do NOT fire when "edges" is present — that is a PIPE edge property
        # query (e.g. "are all PIPE edges UNKNOWN?") → connectivity_topology.
        _is_count = bool(t & {"how", "many", "count", "total", "quantity"})
        _pipe_only = bool(t & _PIPE_SUBJECTS) and not bool(
            t & _VALVE_SUBJECTS or t & _EQUIPMENT_SUBJECTS
        )
        _has_edges = bool(t & {"edge", "edges"})
        # Guard: "show forward flow pipe segments" = line_attributes descriptor query.
        # "forward"/"reverse" are flow VALUE words, not flow CONCEPT words.
        # When they appear with pipe subjects and no "direction" concept word, the
        # user is filtering pipe segments by their flow-direction attribute → line_attributes.
        _fwd_rev_pipe_desc = bool(
            t & {"forward", "reverse"}
            and t & _PIPE_SUBJECTS
            and "direction" not in t
        )
        if _pipe_only and not _is_count and not _has_edges and (t & _CROSS_DOMAIN_ANCHORS["flow"]) and not _fwd_rev_pipe_desc:
            return "flow_direction"
        if _fwd_rev_pipe_desc and _pipe_only and not _is_count:
            return "line_attributes"

        # ── 5. Connectivity quality — boolean "are all X connected?" ──────
        # "are all pipes connected?" → drawing_consistency (pre-computed checks).
        # Excludes "what is this drawing connected to?" — that is an external
        # interface question (the drawing as a boundary, not a connectivity check).
        # "what is this drawing connected to?" → external_interfaces
        # "connections on this drawing" → NOT external (just topology context)
        if t & {"drawing", "diagram"} and t & {"connected", "connects", "connectivity"}:
            return "external_interfaces"
        # "are all inlets/outlets properly connected?" → external_interfaces.
        # inlet/outlet/interface presence overrides the connectivity quality check —
        # degree-1 on inlet/outlet is CORRECT behaviour, not a defect.
        if t & {"inlet", "outlet", "inlets", "outlets",
                "interface", "interfaces"} and t & {"connected", "connects",
                                                     "connectivity", "properly",
                                                     "connection", "connections"}:
            return "external_interfaces"
        # "Are all external interfaces degree=1?" → external_interfaces.
        # degree-1 on interface nodes is the correct design — not a topology query.
        if t & {"inlet", "outlet", "inlets", "outlets",
                "interface", "interfaces"} and t & {"degree"}:
            return "external_interfaces"
        # Only treat as quality check when a STRONG boolean verb is present
        # ("are all X connected?", "is everything connected?", "verify connectivity").
        # Exclude "all"/"every" to avoid catching "show all PIPE connections".
        # Fix 6: also exclude when 2+ distinct equipment domains are present —
        # "which instruments are connected to valves?" is a cross-domain topology
        # query, not a connectivity consistency check.
        # Fix: "What is connected to tank67?" is a directional neighbour query,
        # NOT a boolean connectivity check.  When "what"/"which"/"show" is present,
        # the user asks WHAT connects, not WHETHER everything is connected.
        _STRONG_BOOLEAN = {"are", "is", "verify", "check", "confirm",
                           "ensure", "fully", "properly"}
        # "how" is a count/directional word ("how many valves are connected?") —
        # not a boolean assertion, so it must NOT route to drawing_consistency.
        _DIRECTIONAL_QUERY = {"what", "which", "show", "list", "display", "give", "how"}
        if ((t & self._CONNECTIVITY_QUALITY_WORDS)
                and (t & _STRONG_BOOLEAN)
                and not (t & _DIRECTIONAL_QUERY)
                and not (t & _ARROW_SUBJECTS)
                and _count_domains(t) < 2):
            return "drawing_consistency"

        # ── 5.5. "bbox" is exclusively a Node property → always engineering_inventory ──
        # Must be BEFORE step 6 cross-domain so "SYMBOL nodes with label and bbox"
        # doesn't get pulled into cross_domain by label+symbol = 2 domain match.
        if "bbox" in t:
            return "engineering_inventory"

        # ── 6. Cross-domain — multiple equipment/flow domains ────────────
        # e.g. "valves on segments with unknown flow" = valve + pipe + flow.
        # Requires a linking word so "flow direction on segment LPS_42"
        # (one concern, two domain words) is not promoted to cross_domain.
        # Arrow + LPS → always flow_direction (arrow evidence on pipe lines).
        # Must check before cross_domain because arrow+LPS is a specific pattern.
        if t & _ARROW_SUBJECTS and t & _PIPE_SUBJECTS:
            return "flow_direction"

        # "connected" + 2 equipment domains → always cross_domain
        # e.g. "Show tanks connected to valves" / "tanks on segments with flow"
        # Guard: equipment + flow-only (no pipe subject) = Node-level flow query
        # (valve/tank/instrument with resolved flow direction → flow_direction).
        _flow_only_second = (
            _count_domains(t) == 2
            and bool(t & _CROSS_DOMAIN_ANCHORS["flow"])
            and not bool(t & _PIPE_SUBJECTS)
        )
        # Fix 6: instrument + valve + connected = cross_domain, NOT drawing_consistency.
        # "which instruments are connected to valves?" has "connected" which is in
        # _CONNECTIVITY_QUALITY_WORDS and would fire drawing_consistency via step 2
        # if not intercepted here. Two distinct equipment domains + link word → cross_domain.
        # ── 6.5. Node-specific connectivity — "what TYPE connected to NODEID?" ────
        # Must come BEFORE step 6 (cross_domain) because "what tanks are connected
        # to instrument5?" has 2 equipment domains (tank + instrument from expansion)
        # which would fire cross_domain before we can intercept it here.
        # When a specific node ID or tag is in the question (e.g. "tank67", "valve3")
        # AND the user is asking about connections, route to connectivity_topology.
        # The __node_id_present guard ensures generic type-vs-type questions like
        # "which instruments are connected to valves?" (no node ID) still fall
        # through to cross_domain below.
        # Excludes boolean quality checks ("is tank1 connected?") — those were
        # already caught at step 5 via _STRONG_BOOLEAN + _DIRECTIONAL_QUERY logic.
        #
        # Also catches directed reachability: "what is downstream of pump X?",
        # "upstream of valve Y?", "trace the path from tank X to valve Y?"
        # These have a node ID and a direction/path word — they are topology queries,
        # NOT flow-state queries.  Without this guard they would fall to step 8's
        # _FLOW_TRIGGER which returns flow_direction just because "upstream"/
        # "downstream" appears, causing the LLM to return arrow nodes.
        _CONNECTIVITY_TRIGGERS = {
            "connected", "connects", "connect", "connection", "connections",
            "upstream", "downstream",
            "path", "reach", "reaches", "reachable", "reachability",
        }
        if "__node_id_present" in t and (t & _CONNECTIVITY_TRIGGERS):
            return "connectivity_topology"

        _multi_domain_link = _CROSS_DOMAIN_LINK_WORDS | {"connected", "connecting"}
        if not _flow_only_second and _count_domains(t) >= 2 and (t & _multi_domain_link):
            return "cross_domain"

        # ── 7. Subject-aware count routing ───────────────────────────────
        if _is_count:
            count_intent = self._count_intent_for_subject(t)
            if count_intent:
                return count_intent

        # ── 8. Non-count routing — most specific first ───────────────────

        # Fix C: "Show all PIPE connections from valve nodes" → connectivity_topology.
        # "from" is not in _CROSS_DOMAIN_LINK_WORDS so step 6 doesn't catch this.
        # connections + pipe + valve + from/all = PIPE edge topology query, not valve query.
        if t & {"connections"} and t & _PIPE_SUBJECTS and t & _VALVE_SUBJECTS and t & {"from", "all"}:
            return "connectivity_topology"

        # Fix 6: rarity/motif words preempt "label" (in _INSTRUMENT_SUBJECTS) so
        # "rarity label distribution" → redundancy_patterns, not instrument_attachment.
        if t & {"rarity", "rare", "rarest", "motif", "motifs", "dominant", "architecturally",
                "normalized_ratio", "absolute_count"}:
            return "redundancy_patterns"
        if t & {"rarest", "rare", "rarity"} and t & {
            "pattern", "patterns", "neighbourhood", "neighborhood", "local"
        }:
            return "redundancy_patterns"

        # Fix B: "Show a full breakdown of every node label and its count"
        # "label" is in _INSTRUMENT_SUBJECTS. Guard: "breakdown"+"node"+"label" context
        # unambiguously means a node-label inventory → engineering_inventory.
        if "breakdown" in t and t & {"node", "nodes"} and t & {"label", "labels"}:
            return "engineering_inventory"

        # Annotation requests — intercept before valve/instrument/duplicate routing.
        if t & {"request", "requests"}:
            return "annotation_requests"

        # PIPE edge/connection queries — topology, not flow direction.
        # Must come before the flow trigger check (step 8 flow block) because
        # "Are all PIPE edges UNKNOWN?" has both "edges" and "flow"+"direction".
        # Fix C: guard "connections+pipe" so it does NOT fire when a valve subject
        # is the primary subject. "Which valve has the most pipe connections?" →
        # valve_placement, not connectivity_topology.
        if t & {"edge", "edges"} and t & _PIPE_SUBJECTS:
            return "connectivity_topology"
        if t & {"connections"} and t & _PIPE_SUBJECTS and not t & _VALVE_SUBJECTS:
            return "connectivity_topology"

        # Flow direction / evidence — before pipe because "which pipes don't
        # have a flow direction?" / "flow confidence for each pipe?" are flow
        # questions even though they mention pipes.
        # "evidence" only fires flow_direction when combined with flow/arrow/direction;
        # standalone "Evidence nodes" queries should go to cross_domain.
        _FLOW_TRIGGER = {"direction", "flow", "upstream", "downstream", "confidence",
                         "seeded", "propagated", "directed", "directional", "drawn",
                         "forward", "reverse"}  # direction values used in specific queries
        _has_flow_trigger = bool(t & (_FLOW_TRIGGER | _ARROW_SUBJECTS))
        _has_evidence_ctx = bool(
            "evidence" in t
            and (t & (_FLOW_TRIGGER | _ARROW_SUBJECTS | _PIPE_SUBJECTS))
        )
        # "direction observation annotation" → flow_coverage (not flow_direction)
        # The word "observation" or "annotation" signals we're querying Annotation nodes,
        # not raw direction data. Override flow_direction if pipe subject + annotation ctx.
        if (_has_flow_trigger or _has_evidence_ctx):
            if t & {"observation", "annotation", "annotations"} and _flow_subj:
                return "flow_coverage"
            # "show all arrows" = arrow node inventory (Node.label='arrow').
            # Only route to flow_direction when explicit flow vocabulary is present
            # alongside the arrow subject (e.g. "show arrows with low confidence").
            if t & _ARROW_SUBJECTS and not t & _FLOW_TRIGGER:
                return "engineering_inventory"
            # Guard: "show FORWARD FLOW PIPE SEGMENTS" = line_attributes (attribute of a
            # pipe segment), not a flow direction query.  Only the direction VALUE words
            # (forward/reverse) are present; no directional concept words → line_attributes.
            _only_direction_value = bool(
                t & {"forward", "reverse"}
                and not (t & {"direction", "upstream", "downstream", "confidence",
                               "seeded", "propagated", "directed", "directional", "drawn"})
            )
            if _only_direction_value and t & _PIPE_SUBJECTS and not t & _VALVE_SUBJECTS:
                return "line_attributes"
            return "flow_direction"

        # Valve
        # Preempt: "Show all PIPE connections from valve nodes" / "PIPE edges from X" →
        # connectivity_topology, not valve_placement.
        # BUT: "Which valve has the most pipe connections?" is a valve query —
        # guard: only fire when valve is NOT the primary subject.
        if t & {"edge", "edges"} and t & _PIPE_SUBJECTS:
            return "connectivity_topology"
        if t & {"connections"} and t & _PIPE_SUBJECTS and not t & _VALVE_SUBJECTS:
            return "connectivity_topology"
        if t & _VALVE_SUBJECTS:
            # Valve + junction language can describe PipeSegment JOINS_AT topology
            # (e.g., "Which pipe segments meet at a valve junction?"). Keep this
            # override before the generic valve route.
            _junction_words_v = {"junction", "junctions", "t-junction", "t-junctions",
                                 "tee", "tees", "branch", "branches",
                                 "manifold", "high-degree", "high_degree"}
            _crossing_words_v = {"crossing", "crossings", "joins", "adjacent", "adjacency"}
            _joins_at_ctx_v = t & {"segment", "segments", "meet", "meets",
                                   "share", "shared", "between", "at", "graph"}
            if t & _crossing_words_v and _joins_at_ctx_v:
                return "segment_junction_topology"
            if t & _junction_words_v and t & _PIPE_SUBJECTS and _joins_at_ctx_v:
                return "segment_junction_topology"
            return "valve_placement"

        # Instrument
        # Guard: "labels" in annotation/request context → annotation_requests.
        # Guard: "label" + "symbol"/"bbox" = Node properties query → engineering_inventory.
        if t & _INSTRUMENT_SUBJECTS:
            if t & {"label", "labels"} and t & {"annotation", "request", "requests"}:
                return "annotation_requests"
            if t & {"label", "labels"} and t & {"symbol", "symbols", "bbox", "node", "nodes"}:
                return "engineering_inventory"
            return "instrument_attachment"

        # Junction / crossing — before pipe subjects because "pipe crossings"
        # has both "pipe" and "crossing"; crossing is the more specific intent.
        #
        # Three sub-cases:
        #   1. LPS adjacency graph → line_attributes
        #   2. JOINS_AT topology (segments meeting at a point) → segment_junction_topology
        #   3. Structural inventory LIST (show all T-junction nodes) → cross_domain
        #      GroundedGenerator builds Annotation.type query; avoids registry AmbiguityError.
        #   4. Structural annotation COUNT (how many T-junction annotations?) → drawing_consistency
        _junction_words_8 = {"junction", "junctions", "t-junction", "t-junctions",
                             "tee", "tees", "branch", "branches",
                             "manifold", "high-degree", "high_degree"}
        _crossing_words_8 = {
            "crossing", "crossings", "joins", "join", "joining",
            "adjacent", "adjacency",
        }
        if t & (_junction_words_8 | _crossing_words_8):
            # 1. LPS adjacency graph or adjacency list → line_attributes
            # (q5_10_lps_adjacency_graph is registered as line_attributes)
            if "adjacency" in t and t & {"lps", "logical"}:
                return "line_attributes"
            # 2. JOINS_AT topology — pipe segments sharing a junction point.
            # Triggered by crossing words OR by junction words combined with
            # pipe/segment context (e.g. "junctions shared between pipe segments",
            # "PipeSegment junction graph").
            _joins_at_ctx = t & {"segment", "segments", "meet", "meets",
                                  "share", "shared", "between", "at", "graph"}

            # "adjacent LPS" (without "graph") → line_attributes
            if ("adjacency" in t or "adjacent" in t) and t & {"lps", "logical"}:
                return "line_attributes"
            if t & _crossing_words_8 and _joins_at_ctx:
                return "segment_junction_topology"
            if t & _junction_words_8 and t & _PIPE_SUBJECTS and _joins_at_ctx:
                return "segment_junction_topology"
            _list_j  = bool(t & {"show", "list", "all", "display", "give"})
            _count_j = bool(t & {"how", "many", "count", "total", "quantity"})
            # "show all crossings" without pipe/topology context = crossing symbol
            # inventory (Node.label='crossing'), not a JOINS_AT topology query.
            # Topology crossings always come with pipe/segment context words.
            if t & {"crossing", "crossings"} and _list_j and not _count_j \
                    and not t & _junction_words_8 and not t & _PIPE_SUBJECTS:
                return "engineering_inventory"
            # 3. Structural inventory list → cross_domain
            if t & _junction_words_8 and _list_j and not _count_j:
                return "cross_domain"
            # 4. Count of annotation type / general annotation inventory
            if t & {"annotation", "annotations"} or _count_j:
                return "drawing_consistency"
            # Default: JOINS_AT junction queries
            return "segment_junction_topology"

        # Degree topology — "degree" queries are always connectivity questions.
        # Guard: not when "degree" appears in engineering_correctness context
        # (e.g. "degree-3 valves") which is already caught by step 1.5.
        if "degree" in t and not (t & _VALVE_SUBJECTS and t & {"3", "4", "5"}):
            return "connectivity_topology"

        # LPS + external → external_interfaces before pipe subject wins
        if t & {"external", "interface", "interfaces"} and t & _PIPE_SUBJECTS:
            return "external_interfaces"

        # Redundancy / rarity — before pipe subjects because "redundant pipe patterns"
        # and "duplicate segments" have pipe words but the question is about
        # structural redundancy, not segment attributes.
        # Exception: "duplicate nodes/symbols" already handled above → drawing_consistency.
        if t & {"redundant", "redundancy", "identical", "rare", "rarest", "rarity",
                "motif", "dominant", "frequency", "architecturally"}:
            return "redundancy_patterns"
        if t & {"rarest", "rare", "rarity"} and t & {
            "pattern", "patterns", "neighbourhood", "neighborhood", "local"
        }:
            return "redundancy_patterns"
        # Fix E: "duplicate geometry_hash segments" → line_attributes (PipeSegment property check),
        # not redundancy_patterns. geometry_hash is a PipeSegment field, not a structural pattern.
        if t & {"duplicate", "duplicates"} and t & {"geometry", "hash"} and t & _PIPE_SUBJECTS:
            return "line_attributes"
        if t & {"duplicate", "duplicates"} and not (t & {"node", "nodes", "symbol", "symbols"}):
            return "redundancy_patterns"

        # Pipe / segment
        if t & _PIPE_SUBJECTS:
            return "line_attributes"

        # Evidence node queries → cross_domain (Evidence is not an equipment node).
        # Must check before _EQUIPMENT_SUBJECTS because Evidence queries often mention
        # equipment context ("equipment semantics", "which tanks generated Evidence").
        if "evidence" in t:
            return "cross_domain"

        # External interfaces — BEFORE generic equipment so "what equipment does each
        # external interface connect to?" routes to external_interfaces, not engineering_inventory.
        if t & {"external", "boundary", "interface", "interfaces", "outside",
                "offplot", "import", "export", "inlet", "outlet",
                "inlets", "outlets"}:
            return "external_interfaces"

        # Generic equipment (tank, pump, vessel …)
        if t & _EQUIPMENT_SUBJECTS:
            return "engineering_inventory"

        # Connectivity / path — specific node queries ("what connects to valve94?")
        if t & {"connected", "connects", "connection", "connections", "path",
                "between", "topology", "route", "reaches",
                "neighbour", "neighbours", "neighbor", "neighbors", "adjacent"}:
            return "connectivity_topology"

        # Duplicate NODES specifically → annotation_requests (DUPLICATE_BBOX AnnotationRequest),
        # not drawing_consistency (which uses Annotation nodes).
        if t & {"duplicate", "duplicates"} and t & {"node", "nodes", "symbol", "symbols"}:
            return "annotation_requests"

        # Redundancy / rarity patterns (remaining cases — parallel, bypass, etc.)
        if t & {"parallel", "bypass", "identical", "redundant", "redundancy",
            "rare", "rarest", "rarity", "motif", "dominant", "frequency", "architecturally"}:
            return "redundancy_patterns"

        # Isolation / reachability fallback
        if t & {"component", "components", "island", "islands",
                "reachable", "reachability", "unreachable"}:
            return "isolation_reachability"

        # Annotation requests / raw review flags
        if t & {"request", "requests", "flagged", "flag", "anomaly", "pending"}:
            return "annotation_requests"

        # ── Fallback: entity reference with no other intent signal ────────
        # When the user mentions a specific node (connector5, FV-001) but
        # the question doesn't match any intent bucket, assume they want
        # to know about that node's topology/connections or inventory info.
        # "What type is connector5?"  → engineering_inventory
        # "Show details for FV-001"   → engineering_inventory
        if t & {"type", "types", "details", "detail", "info", "information",
                "label", "properties", "about", "describe"}:
            return "engineering_inventory"

        return "unknown_intent"

    def _count_intent_for_subject(self, t: Set[str]) -> Optional[str]:
        """
        For a count question, return the correct intent based on WHAT
        is being counted, checking most-specific subjects first.
        Returns None if no subject is found (caller continues normal routing).
        """
        # Fix B: "Show a full breakdown of every node label and its count"
        # "label" is in _INSTRUMENT_SUBJECTS but "breakdown"+"node"+"label"
        # unambiguously means a node-label inventory query → engineering_inventory.
        if "breakdown" in t and t & {"node", "nodes"} and t & {"label", "labels"}:
            return "engineering_inventory"

        # AnnotationRequest count queries ("how many open annotation requests?")
        if t & {"request", "requests"} and not t & _VALVE_SUBJECTS:
            return "annotation_requests"

        # Junction / crossing — check BEFORE pipe subjects because
        # "how many pipe crossings?" has both "pipe" and "crossing".
        # BUT: "how many crossing nodes?" = Node.label inventory → engineering_inventory.
        # Structural annotation type count → drawing_consistency (Annotation.type count).
        # JOINS_AT topology count with "meet/segment" → segment_junction_topology.
        _junction_words_c = {"junction", "junctions", "t-junction", "t-junctions",
                             "tee", "tees", "branch", "branches",
                             "manifold", "high-degree", "high_degree"}
        _crossing_words_c = {"crossing", "crossings", "join", "joins", "joining"}
        if t & (_junction_words_c | _crossing_words_c):
            # "How many crossing nodes?" = Node.label='crossing' count
            if t & {"crossing", "crossings"} and t & {"node", "nodes"}:
                return "engineering_inventory"
            # JOINS_AT count (pipe segments at a valve junction, pipe crossings)
            if t & {"segment", "segments", "meet", "meets", "at"} and t & _PIPE_SUBJECTS:
                return "segment_junction_topology"
            # Structural annotation type count → drawing_consistency
            if t & {"annotation", "annotations"} or t & _junction_words_c:
                return "drawing_consistency"
            # Crossing count without junction words → segment_junction_topology
            return "segment_junction_topology"

        # PIPE edge/degree counts → connectivity_topology
        if t & {"edge", "edges"} and t & _PIPE_SUBJECTS:
            # LPS-level adjacency edges = ADJACENT_VIA_NODES → line_attributes
            if ("adjacency" in t or "adjacent" in t) and t & {"lps", "logical"}:
                return "line_attributes"
            return "connectivity_topology"

        # Degree count → connectivity_topology
        if "degree" in t:
            return "connectivity_topology"

        # LPS + arrow/evidence count → flow_direction (arrow evidence query)
        if t & _PIPE_SUBJECTS and t & ({"arrow", "arrows", "evidence"}):
            return "flow_direction"

        # LPS + valve count → cross_domain (multi-entity join)
        if t & _PIPE_SUBJECTS and t & _VALVE_SUBJECTS:
            return "cross_domain"

        # Pipe / segment → line_attributes (LogicalPipeSegment node)
        if t & _PIPE_SUBJECTS:
            return "line_attributes"

        # Valve → valve_placement (Equipment WHERE type CONTAINS 'valve')
        if t & _VALVE_SUBJECTS:
            return "valve_placement"

        # Instrument / annotation → instrument_attachment (Annotation node)
        if t & _INSTRUMENT_SUBJECTS:
            return "instrument_attachment"

        # Arrow — counting arrows as symbols → engineering_inventory
        # ("how many arrows" = symbol count, not a flow direction query)
        # Non-count arrow queries fall through to flow_direction in the
        # non-count routing path below.
        if t & _ARROW_SUBJECTS:
            return "engineering_inventory"

        # Junction / crossing → segment_junction_topology
        if t & {"junction", "junctions", "t-junction", "t-junctions",
                "crossing", "crossings", "tee", "tees",
                "branch", "branches"}:
            return "segment_junction_topology"

        # External interfaces
        if t & {"external", "interface", "interfaces", "inlet", "outlet",
                "boundary", "offplot"}:
            return "external_interfaces"

        # Isolation / components
        if t & {"isolated", "component", "components", "island", "islands",
                "disconnected", "unreachable"}:
            return "isolation_reachability"

        # Motif / rarity → redundancy_patterns (before generic equipment)
        if t & {"motif", "motifs", "rare", "rarest", "rarity", "dominant",
                "architecturally", "esv", "kav"}:
            return "redundancy_patterns"

        # SYMBOL nodes with flow direction = Node-level flow count
        if t & {"symbol", "symbols"} and t & {"flow", "direction", "resolved",
                                               "seeded", "propagated"}:
            return "flow_direction"

        # Generic equipment → engineering_inventory (Equipment node)
        if t & _EQUIPMENT_SUBJECTS:
            return "engineering_inventory"

        # Bare "how many" with no clear subject → generic inventory
        if t & {"how", "many", "count", "total"}:
            return "engineering_inventory"

        return None

    # ------------------------------------------------------------------
    # Slot extraction
    # ------------------------------------------------------------------

    def _extract_slots(self, question: str) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}

        # Equipment tag (FV-001, PSV-A-123)
        if tag := TAG_RE.search(question):
            slots["tag"] = tag.group(0)

        # Inline node ID (tank67, valve12, connector5) — use as tag if no
        # equipment tag was found.  When multiple node IDs are present
        # (e.g. "path between tank67 and valve12"), store first as tag and
        # all of them in a dedicated slot for path queries.
        node_id_matches = NODE_ID_RE.findall(question)
        if node_id_matches:
            # Normalize spaces: "tank 70" → "tank70"
            normalised = [re.sub(r"\s+", "", m) for m in node_id_matches]
            if "tag" not in slots:
                slots["tag"] = normalised[0]
            if len(normalised) >= 2:
                slots["node_ids"] = normalised

        if numbers := NUMBER_RE.findall(question):
            slots["numbers"] = numbers

        if systems := SYSTEM_RE.findall(question):
            slots["system_candidates"] = systems[:4]

        return slots