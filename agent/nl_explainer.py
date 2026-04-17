# agent/nl_explainer.py
"""
NL Explainer — Layer 5b

LLM-powered natural language wrapper grounded in the Phase-6 trace.
LLMClient Protocol and GroqClient implementation live in agent/llm_client.py.

The trace is the source of truth for the explanation.
The LLM's job is to translate it into engineer language — not to reason
freely from the raw records.

Grounding strategy:
    The system prompt instructs the LLM to use the trace as its anchor:
      - steps[].intent       → what was looked up and why
      - steps[].result_stats → how many rows/nodes/relationships
      - summary.statement    → the neutral factual conclusion
      - provenance           → which drawing, which graph version

    Raw records are provided only as supporting detail (up to 20 rows,
    sanitized — no internal graph IDs or property names).

    The LLM must not add conclusions, safety judgements, or inferences
    beyond what the trace contains.

Fallback:
    If the LLM call fails or returns empty, SimpleExplainer is used.
    SimpleExplainer uses only the raw records — no trace context.

Change vs previous version:
    _distill_trace maps step["intent"] → distilled["steps"][n]["what"].
    step["intent"] now contains the generator's human-readable reasoning string
    (e.g. "Counted SYMBOL nodes with degree=1 via CONNECTED list comprehension")
    rather than an opaque query title. The distillation logic is unchanged —
    the richer content arrives automatically from TraceAdapter.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Any, Optional

from agent.llm_client import LLMClient
from agent.query_registry import QueryEntry
from agent.simple_explainer import SimpleExplainer
from agent.property_translations import PROP_TRANSLATIONS, HIDDEN_PROPS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record sanitizer
# ---------------------------------------------------------------------------

# Note: HIDDEN_PROPS and PROP_TRANSLATIONS are now imported from property_translations.py
# to maintain a single source of truth shared with SimpleExplainer


_ANNOTATION_TYPE_LABELS = {
    "pipe_segment_no_evidence_via_lps": "pipe run unreachable by flow evidence",
    "dead_end_pipe_segment":            "dead-end pipe run",
    "structural_branch":                "branch point",
    "structural_t_junction":            "T-junction",
    "structural_high_degree":           "high-connection point",
    "ps_unreachable_from_evidence":     "pipe run unreachable from evidence",
    "pipe_segment_no_logical_mapping":  "pipe run with no pipe line mapping",
    "lps_low_confidence_evidence":      "low-confidence flow direction",
    "orphan_node":                      "orphaned symbol",
    "pipe_segment_cycle_member":        "pipe run in cycle",
    "large_manifold_node":              "large manifold point",
    "endpoint_collision":               "endpoint collision",
    "rare_motif_local":                 "rare local topology pattern",
    "structural_pattern_rarity":        "unusual topology pattern",
    "structural_pattern_frequency":     "common topology pattern",
    "direction_observation":            "flow direction observation",
    "direction_frequency_summary":      "flow direction summary",
    "pipe_junction":                    "pipe junction",
    "DUPLICATE_BBOX":                   "duplicate bounding box",
    "ORPHAN_NODE":                      "orphaned symbol",
    "DANGLING_INLINE":                  "dangling inline symbol",
}

# Keys whose VALUES should be translated through _ANNOTATION_TYPE_LABELS
_TRANSLATE_VALUE_KEYS = {"issue", "issue type", "issue_type", "type", "anomaly_type",
                         "issue type", "pattern", "pattern type", "annotation_type"}


class RecordSanitizer:
    """Strips internal graph properties and translates prop names."""

    def sanitize(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for record in records:
            clean: Dict[str, Any] = {}
            for key, value in record.items():
                if key in HIDDEN_PROPS:
                    continue
                display = PROP_TRANSLATIONS.get(key, key)
                # Translate annotation type values so engineers see plain labels
                if display in _TRANSLATE_VALUE_KEYS and isinstance(value, str):
                    value = _ANNOTATION_TYPE_LABELS.get(value, value)
                clean[display] = value
            if clean:
                cleaned.append(clean)
        return cleaned


# ---------------------------------------------------------------------------
# Trace distiller
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Trace text cleaner — engineering language safety net
# ---------------------------------------------------------------------------

# Applied to every trace "finding" and "step.what" field.
# Catches implementation terms that arrive via LLM-generated reasoning
# (GroundedGenerator) or residual SchemaGenerator strings.
_TRACE_TERM_SUB: List[tuple] = [
    # Class / node type names
    ("LogicalPipeSegment",   "pipe line"),
    ("PipeSegments",         "pipe runs"),
    ("PipeSegment",          "pipe run"),
    ("AnnotationRequest",    "drawing quality request"),
    ("SYMBOL nodes",         "equipment symbols"),
    ("SYMBOL node",          "equipment symbol"),
    ("Node records",         "symbols"),
    ("Node record",          "symbol"),
    # Relationship names
    ("ENDPOINT_OF",          "pipe endpoint"),
    ("FLOW_EVIDENCE",        "arrow flow evidence"),
    ("ADJACENT_VIA_NODES",   "adjacent pipe"),
    ("ANNOTATES",            "flags"),
    ("-[:COVERS]->",         "covers"),
    ("-[:CONTAINS]->",       "contains"),
    ("JOINS_AT",             "joins at"),
    ("HAS_ANNOTATION",       "has request"),
    ("[:PIPE]",              "pipe"),
    # Property values / pipeline jargon
    ("flow_state='UNKNOWN'",                    "no resolved flow direction"),
    ("flow_state = \'UNKNOWN\'",              "no resolved flow direction"),
    ("flow_state IN [\'SEEDED\',\'PROPAGATED\']", "confirmed flow direction"),
    ("flow_state",                              "flow status"),
    ("flow_direction",                          "flow direction"),
    ("flow_confidence",                         "flow confidence"),
    ("geometry_hash",                           "geometry fingerprint"),
    ("component_id",                            "network section ID"),
    ("structural_type",                         "symbol class"),
    ("phase4_hint",                             "pipeline hint"),
    ("flow_source",                             "flow source"),
    ("seed_confidence",                         "seed confidence"),
    ("pre-computed Annotation",                 "pre-analysed issue"),
    ("pre-computed annotation",                 "pre-analysed issue"),
    ("PIPE list comprehension",                 "connection count"),
    ("list comprehension",                      "connection count"),
    ("via ANNOTATES relationship",              ""),
    ("via CONTAINS/COVERS",                     ""),
    ("via ABOUT",                               ""),
    # Annotation type names — translated when they appear in trace text
    ("pipe_segment_no_evidence_via_lps",    "pipe run unreachable by flow evidence"),
    ("dead_end_pipe_segment",               "dead-end pipe run"),
    ("structural_branch",                   "branch point"),
    ("structural_t_junction",               "T-junction"),
    ("structural_high_degree",              "high-connection point"),
    ("ps_unreachable_from_evidence",        "pipe run unreachable from evidence"),
    ("pipe_segment_no_logical_mapping",     "pipe run with no pipe line mapping"),
    ("lps_low_confidence_evidence",         "low-confidence flow direction"),
    ("orphan_node",                         "orphaned symbol"),
    ("endpoint_count_mismatch",             "connection endpoint mismatch"),
    ("pipe_segment_cycle_member",           "pipe run in cycle"),
    ("large_manifold_node",                 "large manifold point"),
    ("endpoint_collision",                  "endpoint collision"),
    ("rare_motif_local",                    "rare local topology pattern"),
    ("structural_pattern_rarity",           "unusual topology pattern"),
    ("structural_pattern_frequency",        "common topology pattern"),
    ("direction_observation",               "flow direction observation"),
    ("direction_frequency_summary",         "flow direction summary"),
    ("pipe_junction",                       "pipe junction"),
]


def _clean_trace_text(text: str) -> str:
    """Replace implementation terms in trace strings with P&ID vocabulary."""
    for old, new in _TRACE_TERM_SUB:
        text = text.replace(old, new)
    return text.strip()


def _distill_trace(traces: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Extract the minimal, LLM-safe subset of the Phase-6 trace.

    Keeps only what anchors the explanation:
        - summary.statement  → the neutral factual conclusion (primary anchor)
        - summary.counts     → the actual count value (e.g. {count: 28})
        - steps[].what       → step["intent"], which now contains the generator
                               reasoning string (e.g. "Counted SYMBOL nodes
                               with degree=1 via CONNECTED list comprehension")
        - steps[].results    → how many rows returned
        - drawing            → which P&ID (if not UNKNOWN)

    Strips: Cypher, file paths, timestamps, trace_id, strategy internals.
    """
    if not traces:
        return None

    trace = traces[0]
    distilled: Dict[str, Any] = {}

    summary = trace.get("summary", {})
    if summary.get("statement"):
        distilled["finding"] = _clean_trace_text(summary["statement"])
    if summary.get("counts"):
        distilled["counts"] = summary["counts"]

    steps = trace.get("steps", [])
    if steps:
        distilled["steps"] = [
            {
                # step["intent"] now contains the generator reasoning string,
                # so the LLM sees the actual traversal description, not a title.
                "what":    _clean_trace_text(s.get("intent", "")),
                "results": s.get("result_stats", {}).get("rows", 0),
            }
            for s in steps
        ]

    prov = trace.get("provenance", {})
    if prov.get("pid_id") and prov["pid_id"] != "UNKNOWN":
        distilled["drawing"] = prov["pid_id"]

    return distilled if distilled else None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """
You are an assistant that explains query results to P&ID (Piping and \
Instrumentation Diagram) engineers.

You will receive:
  1. The engineer's question
  2. A reasoning trace — a structured record of exactly what was queried \
and what was found. This is your source of truth.
  3. Sample result rows (supporting detail only)

Your job:
  - Base your answer PRIMARILY on the trace "finding" field — that is the \
factual anchor
  - Use the trace "steps[].what" to explain what was looked up, if helpful. \
    This field describes the actual graph traversal performed — which symbol \
    types, relationship paths, and filter conditions were used. Translate it \
    into plain engineering language (e.g. "checked all pipe symbols with only \
    one connection").
  - Use "steps[].results" (the row count) to confirm the finding
  - Use sample rows only to give concrete examples (e.g. specific IDs or types)
  - Translate everything into plain engineering language

Rules — never break these:
  - NEVER invent or guess entity names, IDs, or examples that are not present \
in the result rows. If the results only show counts, do not name any specific \
valve, tank, pipe, or symbol — only state the count.
  - Name symbol types precisely from the query context: if the query filtered \
on label='arrow', say "arrow symbols" not "equipment items". \
If label='tank', say "tanks". If label='valve', say "valves".
  - Never mention graph database internals: no Cypher, Neo4j, nodes, edges, \
relationships, labels, traversals, list comprehensions
  - Never mention system internals: no trace_id, lps_id, ps_id, node_id, \
geometry_hash, component_id, or any identifier an engineer would not \
recognise from the drawing itself
  - Never say "the graph shows" or "the database contains" — say \
"the drawing shows" or "on this P&ID"
  - Never add conclusions, safety judgements, or inferences not in the trace
  - If results are empty (count = 0 or no records), say clearly what was \
searched and that nothing was found — do not speculate why
  - Be concise — engineers want direct facts, not narrative
  - NEVER add generic offers to help, introductory sentences, closing remarks,
    or suggestions for follow-up questions. Answer the question asked, then stop.
  - NEVER start your response with "I", "Certainly", "Sure", "As a", "Of course",
    or any similar preamble. Start directly with the answer.

P&ID terminology reference:
  - Symbol types: valve, tank, instrumentation, general, arrow, crossing, inlet/outlet
  - "Arrow symbols" = flow direction indicators on the drawing
  - "Pipe runs" = physical pipe geometry between two symbols
  - "Pipe lines" = semantic pipe paths grouping one or more pipe runs
  - Flow direction: FORWARD or REVERSE — only meaningful when confirmed
  - "Dangling ends" = symbols connected to only one pipe side
  - "Orphaned symbols" = symbols with no pipe connections at all
  - "Junction" = symbol or point with 3 or more pipe connections
  - "External interfaces" = inlet/outlet points at the drawing boundary
  - "Pre-analysed issues" = quality and consistency checks computed by the pipeline
  - "Isolated section" = group of pipe runs disconnected from the main network
  - "Flow coverage" = the proportion of pipe lines whose flow direction has been
    resolved (SEEDED from an arrow, or PROPAGATED from a neighbour). Unresolved
    lines (UNKNOWN) are a normal analysis gap on real P&IDs, not a drawing defect.
    Report them as "X of Y pipe lines have a resolved flow direction (Z%)" — never
    as errors or failures.
  - NEVER use: seeded, propagated, SYMBOL, CONNECTOR, phase4, component_id,
    geometry_hash, structural_type, or any raw property / relationship name
""".strip()


# ---------------------------------------------------------------------------
# NL Explainer
# ---------------------------------------------------------------------------

class NLExplainer:
    """
    LLM-powered natural language explainer grounded in the Phase-6 trace.

    Drop-in replacement for SimpleExplainer — same ExplainerProtocol interface.
    Falls back to SimpleExplainer if LLM is unavailable or returns empty.
    """

    _MAX_RECORDS = 20
    _MAX_TOKENS  = 600   # increased: consistency/list queries can have 10+ rows

    def __init__(
        self,
        llm_client: LLMClient,
        fallback:   SimpleExplainer,
        sanitizer:  RecordSanitizer,
    ) -> None:
        self._llm       = llm_client
        self._fallback  = fallback
        self._sanitizer = sanitizer

    def explain(
        self,
        *,
        question:    str,
        query_entry: QueryEntry,
        intent:      Dict[str, Any],
        records:     List[Dict[str, Any]],
        traces:      List[Dict[str, Any]],
    ) -> str:
        try:
            clean     = self._sanitizer.sanitize(records)
            trace_ctx = _distill_trace(traces)
            # Detect validate operation — question asks for a pass/fail verdict
            is_validate = any(
                w in question.lower()
                for w in ("validate", "valid", "check all", "verify", "consistent",
                          "are all", "is every", "coverage", "does every")
            )
            message   = self._build_message(
                question    = question,
                query_title = query_entry.get("title", "query"),
                trace_ctx   = trace_ctx,
                records     = clean,
                is_validate = is_validate,
                intent_type = intent.get("intent_type", ""),
            )
            response = self._llm.complete(
                system     = _SYSTEM_PROMPT,
                message    = message,
                max_tokens = self._MAX_TOKENS,
            )
            if response and response.strip():
                return response.strip()

            logger.warning("[NLExplainer] Empty LLM response — using fallback")

        except BaseException as exc:
            logger.warning(f"[NLExplainer] LLM call failed ({exc}) — using fallback")

        return self._fallback.explain(
            question=question, query_entry=query_entry,
            intent=intent, records=records, traces=traces,
        )

    def _build_message(
        self,
        *,
        question:    str,
        query_title: str,
        trace_ctx:   Optional[Dict[str, Any]],
        records:     List[Dict[str, Any]],
        is_validate: bool = False,
        intent_type: str  = "",
    ) -> str:
        parts: List[str] = []
        parts.append(f"Engineer's question: {question}")
        parts.append(f"Query performed: {query_title}")

        if is_validate:
            parts.append(
                "\nThis is a VALIDATION question — the engineer wants a pass/fail verdict.\n"
                "\n"
                "CRITICAL — how to count violations:\n"
                "  - The results are GROUPED rows, each with an issue category and a count value.\n"
                "  - N = the SUM of all count values across all rows — NOT the number of rows.\n"
                "  - If every count is 0, the answer is PASS. Otherwise FAIL.\n"
                "\n"
                "Format your answer as:\n"
                "  ✅ PASS — [brief reason]\n"
                "  ❌ FAIL — [total N] issues found across [X] categories:\n"
                "    - [issue category label]: [count]\n"
                "    - [issue category label]: [count]\n"
                "    ... (list every row that has count > 0, using plain P&ID language for the category name)\n"
                "\n"
                "Use the issue and count values directly from the sample results. Do not invent, "
                "interpret, or elaborate on what caused each issue — only state what was found and how many."
            )

        # ── Intent-specific output format instructions ──────────────────
        if intent_type == "flow_coverage":
            parts.append(
                "\nOUTPUT FORMAT for flow coverage:"
                "\n  State the answer as: 'X of Y pipe lines have a resolved flow direction (Z%)'"
                "\n  If asking about unresolved: 'X pipe lines have no resolved flow direction.'"
                "\n  Use the coverage_percent value directly if present. Do NOT recompute it."
                "\n  Do NOT describe this as a problem — unresolved pipe lines are normal on P&IDs."
            )
        elif intent_type == "engineering_correctness":
            parts.append(
                "\nOUTPUT FORMAT for engineering correctness:"
                "\n  For summary results: state each check result in one line each."
                "\n  Format: '[check name]: X [units] [pass/concern]'"
                "\n  For detail results (list of tanks/valves): the IDs shown are internal."
                "\n  State the COUNT."
                "\n  If equipment_role column is present: 'pump' = condensate pump unit,"
                "\n  'tank' = storage vessel/heater. Use this to distinguish, not dimensions."
                "\n  If pump_count and vessel_count are present: state both separately."
                "\n  End with: 'These results are topology-only and require engineer review.'"
            )
        elif intent_type == "isolation_reachability":
            parts.append(
                "\nOUTPUT FORMAT for isolation/reachability:"
                "\n  section_id values (0, 90, 99 etc.) are network section identifiers."
                "\n  Section 0 = main connected network. Others = isolated sub-networks."
                "\n  Use 'main network' for section 0, 'isolated section' for others."
            )

        if trace_ctx:
            parts.append(f"\nReasoning trace:\n{json.dumps(trace_ctx, indent=2)}")
        else:
            parts.append("\nReasoning trace: not available")

        sample   = records[: self._MAX_RECORDS]
        overflow = len(records) - len(sample)
        note     = f" (showing {len(sample)} of {len(records)})" if overflow > 0 else ""

        if sample:
            parts.append(f"\nSample results{note}:\n{json.dumps(sample, indent=2)}")
        else:
            parts.append("\nSample results: none returned")

        parts.append(
            "\nWrite a direct answer to the engineer's question, "
            "grounded in the reasoning trace above."
        )

        return "\n".join(parts)