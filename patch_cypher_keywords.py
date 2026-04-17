"""
Batch-add '// Required keywords:' comments to specific .cypher files.
Run once from the Chatbot project root.
"""
from pathlib import Path

BASE = Path("engine/phase5_cypher")

# Maps relative path (from BASE) → required keywords string
ADDITIONS: dict[str, str] = {
    # ── instruments/ ───────────────────────────────────────────────────────
    # Specialized cross-subject queries: the primary intent bucket is
    # instrument_attachment, but these need a secondary subject to fire.
    "instruments/q3_7_instruments_connected_valves.cypher":            "valve",
    "instruments/q3_8_instruments_connected_tanks.cypher":              "tank",
    "instruments/q3_4_orphan_node_annotations_targeting_instruments.cypher": "orphan",
    "instruments/q3_6_dangling_inline_instrument_annotation_requests.cypher": "dangling",
    "instruments/q3_10_pipe_segments_contain_instrument_nodes.cypher":  "pipe, segment",
    "instruments/q3_11_instruments_grouped_their_component_id.cypher":  "component",

    # ── valves/ ────────────────────────────────────────────────────────────
    "valves/q2_6_valves_directly_connected_tanks.cypher":               "tank",
    "valves/q2_7_valves_directly_connected_instruments.cypher":         "instrument",
    "valves/q2_10_valves_lps_forward_flow.cypher":                      "forward",
    "valves/q2_11_valves_lps_reverse_flow.cypher":                      "reverse",
    "valves/q2_12_valves_structural_high_degree_annotation.cypher":     "degree",
    "valves/q2_9_valves_lps_unknown_flow_direction.cypher":             "unknown",
    "valves/q2_3_valve_most_pipe_connections.cypher":                   "most",
    "valves/q2_4_degree_valve.cypher":                                  "degree",
    "valves/q2_8_logical_pipe_segments_pass_through_valve.cypher":      "pass, through",

    # ── cross_domain/ ─────────────────────────────────────────────────────
    "cross_domain/q19_15_valves_high_severity_annotations_forward_flow.cypher": "forward, valve",
    "cross_domain/q19_1_valves_lps_unknown_flow_direction.cypher":       "valve, unknown",
    "cross_domain/q19_6_valves_both_structural_annotation_unknown_flow.cypher": "valve, structural, unknown",
    "cross_domain/q19_3_tanks_connected_valves_unknown_flow.cypher":     "tank, unknown",
    "cross_domain/q19_7_instruments_flagged_as_dangling_no_flow.cypher": "dangling, instrument",
    "cross_domain/q19_2_instruments_segments_missing_flow_evidence.cypher": "instrument, evidence",
    "cross_domain/q19_9_tank_most_connected_lps.cypher":                 "tank",
    "cross_domain/q19_5_orphan_nodes_also_isolated_pipe_components.cypher": "orphan, isolated",
    "cross_domain/q19_10_esv_annotations_high_degree_nodes.cypher":     "degree",
    "cross_domain/q19_13_kav_annotations_valve_nodes.cypher":           "valve",

    # ── engineering_correctness/ ──────────────────────────────────────────
    "engineering_correctness/q20_5_critical_severity_engineering_violations.cypher": "critical",
    "engineering_correctness/q20_6_pumps_missing_downstream_check_valve_missing.cypher": "pump, check",
    "engineering_correctness/q20_7_pumps_check_valve_within_10_hops.cypher": "pump",
    "engineering_correctness/q20_16_vessels_missing_pressure_relief_valve_violations.cypher": "pressure, relief",
    "engineering_correctness/q20_17_equipment_missing_isolation_valve_violations.cypher": "isolation, missing",
    "engineering_correctness/q20_18_pumps_missing_suction_strainer_missing_suction.cypher": "pump, suction, strainer",

    # ── annotations/ ─────────────────────────────────────────────────────
    "annotations/q13_10_annotation_requests_connector_nodes.cypher":    "connector",
    "annotations/q13_11_annotation_requests_valve_nodes.cypher":        "valve",
    "annotations/q13_12_specific_nodes_flagged_annotation_requests.cypher": "specific, flagged",
    "annotations/q13_14_detail_text_annotation_requests.cypher":        "detail",
    "annotations/q13_6_orphan_node_annotation_requests.cypher":         "orphan",
    "annotations/q13_8_dangling_inline_annotation_requests.cypher":     "dangling",
    "annotations/q16_9_annotations_grouped_intent.cypher":              "intent, grouped",
    "annotations/q16_13_phase4_hint_values_their_annotation_counts.cypher": "phase4, hint",
    "annotations/q16_14_annotations_flagged_as_requires_fallback_rule.cypher": "fallback",
    "annotations/q16_15_annotations_flagged_as_terminate_propagation.cypher": "terminate, propagation",
    "annotations/q16_16_annotations_flagged_as_use_as_traversal.cypher": "traversal",
    "annotations/q16_7_annotations_pipeline_integrity_team.cypher":     "pipeline, integrity",
    "annotations/q16_18_annotations_grouped_source_pipeline_phase.cypher": "pipeline, source",
}

MARKER = "// Required keywords:"

updated = 0
skipped = 0
missing = 0

for rel, keywords in ADDITIONS.items():
    path = BASE / rel
    if not path.exists():
        print(f"[MISSING] {rel}")
        missing += 1
        continue

    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        skipped += 1
        continue  # already has a required keywords comment

    # Insert after the "// Operation:" line
    old_line = next(
        (ln for ln in content.splitlines() if ln.strip().startswith("// Operation:")),
        None,
    )
    if old_line is None:
        # Fall back: insert before the empty line above the Cypher
        new_content = content.replace(
            "//\n\n",
            f"//\n// {MARKER} {keywords}\n\n",
            1,
        )
    else:
        new_content = content.replace(
            old_line,
            f"{old_line}\n// Required keywords: {keywords}",
            1,
        )

    path.write_text(new_content, encoding="utf-8")
    print(f"[UPDATED] {rel} → required: {keywords}")
    updated += 1

print(f"\nDone. updated={updated}, skipped={skipped}, missing={missing}")
