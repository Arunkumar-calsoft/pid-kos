# engine/phase1_segmentation/classify_equipment.py
#
# Phase 1 — Equipment label inference and functional role resolution.
#
# PURPOSE:
#   draw.io exports P&ID symbols with a limited label vocabulary:
#   'connector', 'crossing', 'arrow', 'valve', 'tank', 'instrumentation',
#   'general', 'inlet/outlet', 'background'.
#
#   Many meaningful P&ID equipment types (check valves, strainers, steam traps,
#   orifice plates, filter elements, sight glasses) end up labeled 'general'
#   because they don't match draw.io's known symbol names.
#
#   This module fills two gaps:
#
#   NEW-B: infer_general_equipment_labels
#     Nodes labeled 'general' that are:
#       - float-coord (equipment, not connectors)
#       - small bbox (< 40px wide AND < 40px tall)
#       - degree-2 in the PIPE graph (inline between two connectors)
#     are relabeled 'inferred_check_valve' in Neo4j.  These are the inline
#     symbols most likely to be check valves, strainers, or steam traps.
#     A secondary label 'inferred_inline_equipment' is applied to small
#     float-coord general nodes of degree-1 or degree-0 (terminal equipment).
#     Large general nodes (≥40px) retain their label — they are likely
#     complex equipment (reactors, heat exchangers) that need HITL review.
#
#   NEW-A: resolve_tank_functional_role
#     'tank' nodes with bbox width < 100px represent condensate pump units
#     (CND-PU-xxx) in these P&IDs, not storage vessels. Their pump-level
#     engineering rules (check_valve downstream, suction_strainer upstream)
#     are defined under the 'pump' key in symbol_dictionary.SKID_CONTEXT.
#     This function stamps functional_label='pump' on small tank nodes so
#     engineering_rules.py can apply the correct rule set.
#
# INTEGRATION:
#   Called by run_phase1.py between classify_nodes_structurally (Step 1.3)
#   and validate_pipe_segments (Step 1.4).
#
# IDEMPOTENT: Uses SET — safe to re-run. Does not MERGE or CREATE new nodes.

from typing import Dict, Tuple

# Threshold below which a 'tank' is a pump symbol, not a storage vessel.
# Matches the bbox_width_max=100.0 constant in equipment_flow.py.
_PUMP_TANK_WIDTH_MAX = 100.0

# Upper width limit for heat exchangers / heaters / condensers.
# Tank nodes with 100 <= width < _HX_WIDTH_MAX are heat-exchange apparatus
# (e.g. CND-HTR-161, CND-HTR-166). Nodes wider than this are storage vessels.
_HX_WIDTH_MAX = 450.0

# Size threshold for inline equipment (both dimensions must be below this).
_INLINE_MAX_PX = 40.0


def infer_general_equipment_labels(driver, database: str, pid_id: str) -> Dict[str, int]:
    """
    Relabel 'general' float-coord nodes based on bbox size and graph degree.

    Neo4j properties written:
      n.label             = 'inferred_check_valve'       (small, degree-2)
      n.label             = 'inferred_inline_equipment'  (small, degree-1 or degree-0)
      n.original_label    = 'general'                    (audit trail on all changed nodes)
      n.label_inferred    = true                         (flag for Phase 7 review)

    Large general nodes (bbox ≥ 40px in either dimension) are not relabeled
    but receive n.label_inferred = false as an explicit marker.

    Returns: counts dict {category: count}
    """
    counts = {
        "inferred_check_valve":       0,
        "inferred_inline_equipment":  0,
        "general_retained":           0,
    }

    with driver.session(database=database) as session:

        # ── Fetch all 'general' float-coord nodes with their degree ────────
        rows = session.run(
            """
            MATCH (n:Node {pid_id: $pid_id, label: 'general'})
            WHERE n.coord_system = 'float'
            OPTIONAL MATCH (n)-[:PIPE]-(nb:Node {pid_id: $pid_id})
            WITH n,
                 count(nb)                     AS degree,
                 (n.xmax - n.xmin)             AS bbox_w,
                 (n.ymax - n.ymin)             AS bbox_h
            RETURN n.id AS nid, degree,
                   bbox_w, bbox_h
            ORDER BY n.id
            """,
            pid_id=pid_id,
        ).data()

        for r in rows:
            nid    = r["nid"]
            degree = int(r.get("degree") or 0)
            bbox_w = float(r.get("bbox_w") or 0.0)
            bbox_h = float(r.get("bbox_h") or 0.0)
            is_small = bbox_w < _INLINE_MAX_PX and bbox_h < _INLINE_MAX_PX

            if is_small and degree == 2:
                # Inline between two connectors — most likely check valve,
                # strainer, steam trap, or orifice plate.
                new_label = "inferred_check_valve"
                session.run(
                    """
                    MATCH (n:Node {id: $nid, pid_id: $pid_id})
                    SET n.original_label = 'general',
                        n.label          = $new_label,
                        n.label_inferred = true
                    """,
                    nid=nid, pid_id=pid_id, new_label=new_label,
                )
                counts["inferred_check_valve"] += 1

            elif is_small and degree in (0, 1):
                # Terminal or dangling inline symbol.
                new_label = "inferred_inline_equipment"
                session.run(
                    """
                    MATCH (n:Node {id: $nid, pid_id: $pid_id})
                    SET n.original_label = 'general',
                        n.label          = $new_label,
                        n.label_inferred = true
                    """,
                    nid=nid, pid_id=pid_id, new_label=new_label,
                )
                counts["inferred_inline_equipment"] += 1

            else:
                # Large general node or high-degree — retain label, mark for review.
                session.run(
                    """
                    MATCH (n:Node {id: $nid, pid_id: $pid_id})
                    SET n.label_inferred = false
                    """,
                    nid=nid, pid_id=pid_id,
                )
                counts["general_retained"] += 1

    total_changed = counts["inferred_check_valve"] + counts["inferred_inline_equipment"]
    print(
        f"[PHASE1][CLASSIFY] General label inference for PID={pid_id}: "
        f"inferred_check_valve={counts['inferred_check_valve']}, "
        f"inferred_inline_equipment={counts['inferred_inline_equipment']}, "
        f"general_retained={counts['general_retained']} "
        f"(total relabeled={total_changed})"
    )
    return counts


def resolve_tank_functional_role(driver, database: str, pid_id: str) -> int:
    """
    Stamp functional_label on 'tank' nodes based on bounding-box width:

      width < 100px    → 'pump'          (small condensate pump unit symbols)
      100 ≤ width < 450 → 'heat_exchanger' (heaters, condensers, heat exchangers)
      width ≥ 450px    → 'tank'          (large storage vessels)

    The n.functional_label property is read by engineering_rules.py
    get_equipment_rules_for_pid() to select the correct SKID_CONTEXT rules,
    and by the UI tooltip to render a green "Role:" badge.

    Returns: count of nodes stamped with functional_label='pump'.
    """
    with driver.session(database=database) as session:
        result = session.run(
            """
            MATCH (n:Node {pid_id: $pid_id, label: 'tank'})
            WHERE (n.xmax - n.xmin) < $pump_width_max
            SET n.functional_label = 'pump'
            RETURN count(n) AS c
            """,
            pid_id=pid_id,
            pump_width_max=_PUMP_TANK_WIDTH_MAX,
        )
        rec = result.single()
        pump_count = int(rec["c"]) if rec else 0

    # Medium-width tank nodes are heat-exchange apparatus (heaters, condensers).
    with driver.session(database=database) as session:
        result = session.run(
            """
            MATCH (n:Node {pid_id: $pid_id, label: 'tank'})
            WHERE (n.xmax - n.xmin) >= $pump_max
              AND (n.xmax - n.xmin) < $hx_max
              AND n.functional_label IS NULL
            SET n.functional_label = 'heat_exchanger'
            RETURN count(n) AS c
            """,
            pid_id=pid_id,
            pump_max=_PUMP_TANK_WIDTH_MAX,
            hx_max=_HX_WIDTH_MAX,
        )
        rec = result.single()
        hx_count = int(rec["c"]) if rec else 0

    # Large storage tanks get an explicit 'tank' functional label for clarity.
    with driver.session(database=database) as session:
        session.run(
            """
            MATCH (n:Node {pid_id: $pid_id, label: 'tank'})
            WHERE n.functional_label IS NULL
            SET n.functional_label = 'tank'
            """,
            pid_id=pid_id,
        )

    print(
        f"[PHASE1][CLASSIFY] Tank functional role resolved for PID={pid_id}: "
        f"{pump_count} pump, {hx_count} heat_exchanger, rest=tank"
    )
    return pump_count