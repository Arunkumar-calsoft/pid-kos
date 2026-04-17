"""
Second-pass required keywords patch — addresses remaining ties after first pass.
Run from Chatbot project root.
"""
from pathlib import Path

BASE = Path("engine/phase5_cypher")

ADDITIONS: dict[str, str] = {
    # "show all valves" → still 2-way tie: valve_node_ids vs valve_resolved_flow_direction
    "valves/q2_13_valve_resolved_flow_direction_node_level.cypher": "resolved, direction",

    # "show all symbols" → still 2-way tie: symbol_nodes_bbox vs equipment_symbol_node_ids
    "inventory/q1_2_equipment_symbol_node_ids.cypher": "equipment",

    # "show all HIGH-severity annotations" → 3-way tie, need esv+kav entries restricted
    "annotations/q15_8_esv_annotations_high_hitl_severity.cypher": "esv",
    "annotations/q15_9_kav_annotations_high_hitl_severity.cypher": "kav",

    # "show all annotation requests" → 2-way tie: duplicate_bbox vs topology_inference
    "annotations/q13_4_duplicate_bounding_box_requests.cypher": "duplicate, bounding",
    "annotations/q16_10_topology_inference_annotation_details.cypher": "topology, inference",

    # "Which pumps are missing a check valve?" → wrong queries winning via "which" + "valve" match
    # q20_11 is about tanks-cannot-reach-valve, not pump check valve
    "engineering_correctness/q20_11_tanks_cannot_reach_valve_within_pipe.cypher": "tank, reach",
    # q20_9 is about pumps with no instruments, not check valves
    "engineering_correctness/q20_9_pumps_no_instruments_within_pipe_hops.cypher": "instrument",

    # Additional cross_domain specializations for cleaner routing
    "cross_domain/q19_4_high_severity_annotations_unknown_flow_segments.cypher": "unknown, flow",
    "cross_domain/q19_8_nodes_more_than_one_quality_annotation.cypher": "multiple, quality",
    "cross_domain/q19_11_percentage_symbol_nodes_least_one_quality.cypher": "percentage",
    "cross_domain/q19_12_annotation_types_co_occur_quality_issues.cypher": "occur, co",
}

MARKER = "// Required keywords:"
updated, skipped, missing = 0, 0, 0

for rel, keywords in ADDITIONS.items():
    path = BASE / rel
    if not path.exists():
        print(f"[MISSING] {rel}")
        missing += 1
        continue
    content = path.read_text(encoding="utf-8")
    if MARKER in content:
        skipped += 1
        continue

    old_line = next(
        (ln for ln in content.splitlines() if ln.strip().startswith("// Operation:")),
        None,
    )
    if old_line:
        new_content = content.replace(old_line, f"{old_line}\n// Required keywords: {keywords}", 1)
    else:
        new_content = content.replace("//\n\n", f"//\n// Required keywords: {keywords}\n\n", 1)

    path.write_text(new_content, encoding="utf-8")
    print(f"[UPDATED] {rel} → {keywords}")
    updated += 1

print(f"\nDone. updated={updated}, skipped={skipped}, missing={missing}")
