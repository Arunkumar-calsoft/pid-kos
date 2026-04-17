# agent/trace_adapter.py
"""
Trace Adapter — Layer 5a

Converts query execution results into a Phase-6 TraceBuilder + TraceStep.

Changes vs previous version:
  1. `reasoning` parameter added to build() — populated by HybridOptimizer
     from GeneratorResult.reasoning. Used as step.intent primary value so
     the LLM explainer sees "Counted SYMBOL nodes with degree=1 via PIPE
     list comprehension" instead of "Dangling end count query".
  2. Fallback chain: reasoning → engineer_question → title → question.
  3. All other logic (category mapping, summary builder, context sanitization)
     is unchanged.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

from agent.query_registry import QueryEntry
from engine.phase6_trace.builder.trace_builder import TraceBuilder
from engine.phase6_trace.builder.trace_step    import TraceStep


class TraceAdapter:

    def build(
        self,
        *,
        question:      str,
        records:       List[Dict[str, Any]],
        query_meta:    QueryEntry,
        context:       Dict[str, Any],
        pid_id:        str,
        graph_version: str,
        cypher:        Optional[str] = None,
        strategy:      Optional[str] = None,
        reasoning:     Optional[str] = None,   # NEW — from OptimizerResult.reasoning
    ) -> List[Dict[str, Any]]:

        # ── Category: prefer intent_type over query category ──────────────
        intent_type = context.get("intent_type", "")
        category    = _intent_to_category(intent_type) \
                      or _map_category(query_meta.get("category", ""))

        # ── Context: extract only schema-safe scalars we actually need ────
        trace_context: Dict[str, Any] = {
            "intent_type": intent_type,
            "operation":   query_meta.get("operation", "list"),
        }
        for slot_key, slot_val in context.get("slots", {}).items():
            if isinstance(slot_val, (str, int, float, bool)):
                trace_context[slot_key] = slot_val
            elif isinstance(slot_val, list) and slot_val:
                if isinstance(slot_val[0], (str, int, float, bool)):
                    trace_context[slot_key] = slot_val[0]

        trace = TraceBuilder(
            question_text = question,
            category      = category,
            context       = trace_context,
            pid_id        = pid_id,
            graph_version = graph_version,
        )

        # ── Step: step.intent uses reasoning as primary source ────────────
        # reasoning contains the human-readable generator description, e.g.:
        #   "Counted SYMBOL nodes with degree=1 via PIPE list
        #    comprehension (dangling ends); excluded background nodes."
        # This is far more useful to the LLM than the old query title.
        step_intent = (
            reasoning
            or query_meta.get("engineer_question")
            or query_meta.get("title")
            or question
        )

        query_ref = cypher or f"[FILE] {query_meta.get('cypher_file', 'unknown')}"

        step = TraceStep(
            step_id               = 1,
            intent                = step_intent,
            source_phase          = 5,
            source_file           = (
                "schema_generator"
                if strategy == "schema_generated"
                else query_meta.get("cypher_file", "schema_generated")
            ),
            source_section        = query_meta["id"],
            query                 = query_ref,
            parameters            = {},
            rows                  = len(records),
            nodes_touched         = None,
            relationships_touched = None,
        )

        trace.add_step(step)

        # ── Summary ───────────────────────────────────────────────────────
        statement, counts = _build_summary(query_meta, records, strategy, intent_type)
        trace.set_summary(statement=statement, counts=counts)

        return [trace.build()]


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

_INTENT_TO_CATEGORY: Dict[str, str] = {
    "engineering_inventory":      "inventory",
    "valve_placement":            "valves",
    "instrument_attachment":      "instruments",
    "line_attributes":            "lines",
    "connectivity_topology":      "topology",
    "flow_direction":             "directionality",
    "engineering_correctness":    "quality",          # Phase 8 — topology conformance
    "flow_coverage":              "directionality",   # Phase 8 — analysis completeness
    "external_interfaces":        "external_interfaces",
    "redundancy_patterns":        "redundancy",
    "drawing_consistency":        "quality",
    "isolation_reachability":     "reachability",
    "annotation_requests":        "quality",
    "segment_junction_topology":  "topology",
    "cross_domain":               "inventory",        # Phase 8 — GroundedGenerator handles
    "custom_query":               "inventory",
}

_CATEGORY_FALLBACK: Dict[str, str] = {
    "inventory":      "inventory",
    "valves":         "valves",
    "instruments":    "instruments",
    "lines":          "lines",
    "connectivity":   "topology",
    "topology":       "topology",
    "external":       "external_interfaces",
    "redundancy":     "redundancy",
    "quality":        "quality",
    "consistency":    "quality",
    "reachability":   "reachability",
    "enriched":       "inventory",
}


def _intent_to_category(intent_type: str) -> Optional[str]:
    return _INTENT_TO_CATEGORY.get(intent_type)


def _map_category(raw: str) -> str:
    raw_lower = raw.lower()
    for key, mapped in _CATEGORY_FALLBACK.items():
        if key in raw_lower:
            return mapped
    return "inventory"


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

_COUNT_COLUMNS = {
    "total", "count", "total_valves", "total_instruments", "total_interfaces",
    "total_pipe_segments", "total_logical_segments", "total_connections",
    "total_duplicates", "total_mismatches", "total_orphan_nodes",
    "total_orphan_annotations", "total_unmapped_segments",
    "dangling_ends", "junction_count", "junction_nodes",
    "isolated_nodes", "orphaned_instruments", "orphan_nodes",
    "conflicting_segments", "low_confidence_segments",
    "segments_without_flow", "connected_nodes",
    "total_adjacent_pairs", "uncovered_segments",
    "disconnected_segments",
}


def _extract_count(records: List[Dict[str, Any]]) -> Optional[int]:
    if len(records) != 1:
        return None
    row = records[0]
    for col, val in row.items():
        if col.lower() in _COUNT_COLUMNS and isinstance(val, (int, float)):
            return int(val)
    return None


def _build_summary(
    query_meta:  QueryEntry,
    records:     List[Dict[str, Any]],
    strategy:    Optional[str],
    intent_type: str,
) -> tuple[str, Dict[str, float]]:
    title  = query_meta.get("title", "query")
    source = {
        "template":         "hardcoded template",
        "schema_generated": "schema-generated query",
        "registry_file":    "verified registry query",
    }.get(strategy or "", "query")

    count_val = _extract_count(records)
    if count_val is not None:
        subject = _subject_label(intent_type, records)
        if count_val == 0:
            statement = f"No {subject} found on this drawing."
        else:
            statement = f"Found {count_val} {subject} on this drawing."
        return statement, {"count": float(count_val)}

    if records and len(records) > 1 and all("total" in r for r in records):
        breakdown = ", ".join(
            f"{r.get('type', r.get('direction', r.get('issue_type', '?')))}: "
            f"{r.get('total', 0)}"
            for r in records[:6]
        )
        grand_total = sum(r.get("total", 0) for r in records
                         if isinstance(r.get("total"), (int, float)))
        statement = (
            f"Found {int(grand_total)} items total across "
            f"{len(records)} categories: {breakdown}."
        )
        return statement, {"total": float(grand_total), "categories": float(len(records))}

    if not records:
        return (
            f"Executed {source} '{title}'. No matching records were found.",
            {"records": 0.0},
        )

    n = len(records)
    return (
        f"Executed {source} '{title}', "
        f"returned {n} record{'s' if n != 1 else ''}.",
        {"records": float(n)},
    )


def _subject_label(intent_type: str, records: List[Dict[str, Any]]) -> str:
    if records:
        col = next(iter(records[0]))
        _COL_LABELS = {
            "dangling_ends":           "dangling ends",
            "junction_count":          "junction nodes",
            "junction_nodes":          "junction nodes",
            "total_valves":            "valves",
            "total_instruments":       "instruments",
            "total_interfaces":        "external interfaces",
            "total_pipe_segments":     "pipe segments",
            "total_logical_segments":  "logical pipe segments",
            "isolated_nodes":          "isolated nodes",
            "orphaned_instruments":    "orphaned instruments",
            "total_orphan_nodes":      "orphaned nodes",
            "total_orphan_annotations":"orphaned annotations",
            "disconnected_segments":   "disconnected segments",
            "conflicting_segments":    "segments with flow conflicts",
            "low_confidence_segments": "low-confidence flow segments",
            "segments_without_flow":   "segments without flow annotation",
            "total_duplicates":        "duplicate symbols",
            "total_mismatches":        "endpoint mismatches",
            "total_connections":       "connections",
            "total_adjacent_pairs":    "adjacent segment pairs",
        }
        if col in _COL_LABELS:
            return _COL_LABELS[col]

    _INTENT_LABELS = {
        "engineering_inventory":  "equipment items",
        "valve_placement":        "valves",
        "instrument_attachment":  "instruments",
        "line_attributes":        "pipe segments",
        "connectivity_topology":  "connected nodes",
        "flow_direction":         "flow-annotated segments",
        "external_interfaces":    "external interfaces",
        "redundancy_patterns":    "redundant patterns",
        "engineering_correctness": "engineering issues",
        "drawing_consistency":    "quality issues",
        "isolation_reachability": "reachable nodes",
    }
    return _INTENT_LABELS.get(intent_type, "records")