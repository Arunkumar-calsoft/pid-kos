# agent/property_translations.py
"""
Shared Property Translations

Single source of truth for translating internal property names to
user-friendly labels. Used by both SimpleExplainer and NLExplainer
to ensure consistent property naming regardless of which explainer is active.

DO NOT duplicate these mappings — import from this module.
"""
from typing import Dict, Set

# ---------------------------------------------------------------------------
# Properties to hide from engineers (internal implementation details)
# ---------------------------------------------------------------------------

HIDDEN_PROPS: Set[str] = {
    "lps_id", "ps_id", "node_id", "geometry_hash",
    "graphml_path", "image_path", "synthetic",
    "via_nodes", "via_count", "trace_nodes",
    "motif_chain_count", "neighborhood",
    "first_seen", "last_seen", "created_at",
    "bbox", "xmin", "xmax", "ymin", "ymax",
    "duplicate_of",
    "rarity_score", "pattern_type", "example_ps_pair",
    "flow_source", "seed_confidence",
    "via", "endpoints", "source",
    "low_confidence_flag", "structural_type", "length",
    "x_pos", "connector_id", "hash", "seg_count", "cnt",
}

# ---------------------------------------------------------------------------
# Property name translations: internal → user-friendly
# ---------------------------------------------------------------------------

PROP_TRANSLATIONS: Dict[str, str] = {
    # Basic equipment properties
    "equipment_id":    "tag",
    "equipment_type":  "type",
    "valve_tag":       "tag",
    "valve_type":      "type",
    "segment_status":  "status",
    "flow_state":      "flow",
    "flow_direction":  "direction",
    "attach_status":   "attachment",
    "flow_confidence": "confidence",
    "arrow_id":        "arrow",
    "skid_id":         "skid",
    "plant_id":        "plant",
    "pid_id":          "drawing",
    "label":           "label",
    "type":            "type",
    "total":           "count",
    "how_determined":  "how determined",
    "issue":           "issue",
    "reason":          "reason",
    "count":           "count",
    
    # Extended translations
    "node_count":                           "nodes in run",
    "anomaly_type":                         "issue type",
    "request_id":                           "request",
    "node_type":                            "symbol type",
    "logical_segment":                      "pipe line",
    "valve_id":                             "valve",
    "interface_id":                         "interface",
    "neighbour_id":                         "connected symbol",
    "neighbour_types":                      "connected symbol types",
    "connects_to_types":                    "connected symbol types",
    "via_segment":                          "via pipe line",
    "neighbour_count":                      "connections",
    "junction_kind":                        "junction type",
    "evidence_direction":                   "observed direction",
    "total_logical_segments":               "total pipe lines",
    "total_pipe_segments":                  "total pipe runs",
    "total_orphan_nodes":                   "orphaned symbols",
    "total_unmapped_segments":              "unmapped pipe runs",
    "low_confidence_segments":              "pipe lines with uncertain flow",
    "total_components":                     "isolated sections",
    "segments_in_component":                "pipe runs in section",
    "total_isolated_nodes":                 "isolated symbols",
    "small_component_count":                "small isolated sections",
    "valves_on_flow_filtered_segments":     "matching valves",
    "instruments_on_flow_filtered_segments": "matching instruments",
    "pipe_segments":                        "pipe runs",
    "logical_segments":                     "pipe lines",
    "declared_endpoints":                   "expected connections",
    "found_endpoints":                      "actual connections",
    "path_labels":                          "symbol types on path",
    "types_reached":                        "symbol types reached",
    "reachable_nodes":                      "reachable symbols",
    "segment_a":                            "pipe run A",
    "segment_b":                            "pipe run B",
    "total_nodes":                          "nodes in section",
    "junction_symbol":                      "junction symbol type",
    "total_requests":                       "open quality requests",
    "total_junctions":                      "junction points",
    "total_adjacent_pairs":                 "adjacent run pairs",
    "issue_type":                           "issue",
    "occurrences":                          "count",
    "connected_nodes":                      "connected symbols",
    "high_degree_valves":                   "high-connection valves",
    "segments_without_flow":                "pipe lines without flow direction",
    "orphaned_instruments":                 "orphaned instruments",
    "dangling_ends":                        "dangling ends",
    "total_mismatches":                     "endpoint mismatches",
    "total_interfaces":                     "external interfaces",
    "segment_ids":                          "pipe run IDs",
    "issue":                                "issue type",
    "target_id":                            "target",
    "total_occurrences":                    "occurrences",
    "pipe_connections":                     "pipe connections",
    "component_id":                         "section_id",
    "tank_id":                              "symbol_id",
    "branching_valve":                      "valve_id",
    "width":                                "symbol_width",
    "height":                               "symbol_height",
    "tanks_without_instrument":             "tanks lacking instruments",
    "branching_valves":                     "valves with 3+ connections",
    "boundary_anomalies":                   "boundary interface anomalies",
    "total_tanks":                          "total tanks",
    "flow_direction_resolved":              "pipe lines with flow direction",
    "flow_direction_unresolved":            "pipe lines without flow direction",
    "total_pipe_lines":                     "total pipe lines",
    "coverage_percent":                     "flow coverage %",
    "unresolved_pipe_lines":                "pipe lines without flow direction",
    "conflicting_arrows":                   "pipe lines with conflicting arrows",
    "structurally_isolated":                "structurally isolated pipe lines",
    "tank_without_instrument":              "tank symbol ID",
}

# ---------------------------------------------------------------------------
# Value-level translations: internal Neo4j values → engineer-friendly labels
# Used by explainers to translate raw property values before displaying them.
# ---------------------------------------------------------------------------

VALUE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "flow_state": {
        "SEEDED":         "confirmed on drawing",
        "PROPAGATED":     "inferred from adjacent pipe",
        "UNKNOWN":        "not determined",
        "SEEDED_UNKNOWN": "conflicting arrows — direction unclear",
        "BLOCKED":        "structurally isolated — not applicable",
        "HITL_PENDING":   "awaiting manual review",
    },
    "flow_direction": {
        "FORWARD": "downstream",
        "REVERSE": "upstream",
        "UNKNOWN": "not determined",
    },
    "how_determined": {
        "evidence":             "from drawing arrows",
        "propagated":           "inferred from neighbours",
        "hitl_required":        "manual review required",
        "propagation_blocked":  "structurally isolated",
        "none":                 "no evidence found",
    },
}