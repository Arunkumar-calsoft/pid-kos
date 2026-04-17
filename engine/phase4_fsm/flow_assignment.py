# engine/phase4_fsm/flow_assignment.py
#
# Phase 4 — Flow assignment to equipment Node instances (pid-scoped)
#
# REPLACES: engine/phase4_fsm/ingest_phase4_flow.py
#           engine/phase4_fsm/ingest_phase4_equipment.py  (DROPPED entirely)
#
# WHY ingest_phase4_equipment.py IS DROPPED:
#   It created Equipment nodes which are NOT in our schema.
#   Our schema: equipment is represented as Node instances with labels like
#   'pump', 'tank', 'valve', etc. Phase 3 R4 already wrote FLOW_EVIDENCE for them.
#   No separate Equipment creation is needed or wanted.
#
# WHY ingest_phase4_flow.py IS REPLACED:
#   It propagated flow to Equipment nodes (which don't exist).
#   Correct path in our schema:
#     (n:Node {label ∈ EQUIPMENT_LABELS}) -[:ENDPOINT_OF]-> (lps:LogicalPipeSegment)
#   Phase 3 equipment_flow.py confirms this — it uses ENDPOINT_OF to find the
#   LPS connected to each equipment node.
#
# WHAT THIS MODULE DOES:
#   After Phase 4 FSM has set flow_state on all LPS, this module:
#
#   1. FLOW ASSIGNMENT (assign_flow_to_nodes):
#      Stamps flow_state / flow_direction / flow_confidence onto equipment Node
#      instances via the ENDPOINT_OF path.  For multi-port equipment (connected
#      to >1 LPS, e.g. a pump with inlet+outlet), the LPS with highest
#      flow_confidence is chosen as the flow authority.
#
#   2. RULE VIOLATION SUMMARY (stamp_rule_violations_on_nodes — NEW Phase 3.5):
#      Reads Phase 3.5 engineering_rule_violation Annotations targeting this PID's
#      equipment nodes, and stamps summary properties (has_rule_violations,
#      rule_violation_count, rule_violation_types) directly onto those nodes
#      for convenient Phase 7 HITL querying.
#      The Annotation nodes themselves are Phase 3.5 data and are NOT modified.
#
# INTEGRITY GUARANTEE:
#   Only assigns flow to nodes whose label appears in EQUIPMENT_NODE_LABELS.
#   Crossing nodes, connectors, and background nodes are never touched.
#
# CLEAR CONTRACT (enforced by run_phase4.clear_phase4_data):
#   Properties cleared on re-run:
#     flow_state, flow_direction, flow_confidence, flow_source, flow_pid_id
#     has_rule_violations, rule_violation_count, rule_violation_types
#   The engineering_rule_violation Annotation nodes are Phase 3.5 and are
#   preserved when Phase 4 is cleared.

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ── Equipment labels that receive flow assignment ─────────────────────────────
#
# These are Node.label values for physical equipment — the nodes that
# P&ID engineers care about when asking "what direction does fluid flow
# through this pump / valve / heat exchanger?"
#
# Source of truth: equipment_flow.py EQUIPMENT_LABELS + CHECK_VALVE_LABELS
# plus common additional process equipment labels.
# Keep in sync with engine/phase3_annotation/equipment_flow.py.

EQUIPMENT_NODE_LABELS = [
    # Active rotating equipment (Phase 3 R4)
    "pump", "centrifugal_pump", "compressor", "ejector", "blower", "fan",
    # Storage/process vessels (Phase 3 R4 — small tanks only)
    "tank",
    # Unidirectional valves (Phase 3 R6)
    "check_valve", "nrv", "non_return_valve", "non_return", "check",
    # Manually operated valves
    "valve", "gate_valve", "globe_valve", "ball_valve", "butterfly_valve",
    # Automatically operated valves
    "control_valve", "relief_valve", "safety_valve", "pressure_relief_valve",
    # Process equipment
    "heat_exchanger", "filter", "strainer", "separator",
    # Flow instruments (relevant for flow direction context)
    "flow_meter", "flowmeter", "flow_indicator",
]


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _scalar(session, q: str, params: dict | None = None, key: str = "c") -> int:
    r = session.run(q, **(params or {})).single()
    return int(r[key]) if r and r.get(key) is not None else 0


def _P(pid_id: str) -> dict:
    return {"pid_id": pid_id}


# ── Flow assignment ──────────────────────────────────────────────────────────────

def assign_flow_to_nodes(session, pid_id: str) -> Dict[str, Any]:
    """
    Stamp flow_state / flow_direction / flow_confidence onto equipment Node instances,
    then stamp engineering rule violation summaries for Phase 7 HITL use.

    Path used for flow assignment:
      (n:Node {label ∈ EQUIPMENT_NODE_LABELS})
        -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id})

    Best LPS = the ENDPOINT_OF LPS with highest flow_confidence that has a
    resolved direction (FORWARD or REVERSE).  For a pump with inlet and outlet
    LPS, the outlet LPS (phase3_equipment_semantics FORWARD, higher confidence)
    wins — which is the correct authority for the pump's discharge direction.

    After flow assignment, Phase 3.5 engineering rule violation summaries are
    stamped onto any equipment node that has violation Annotations in this PID.
    This is a read-only pass over Phase 3.5 data — no Annotation nodes are
    created or modified.

    Args:
        session:  open Neo4j session (caller owns lifecycle)
        pid_id:   PID identifier

    Returns:
        summary dict: updated, unassigned, seeded_lps, contaminated,
                      rule_violations_stamped

    Raises:
        RuntimeError if no LPS has flow_state (FSM not yet run).
    """
    logger.info(
        "[PHASE4][FLOW_ASSIGN] Assigning flow to equipment nodes | PID=%s", pid_id
    )

    # ── Guard: FSM must have run ───────────────────────────────────────────────
    seeded_lps = _scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.flow_state IS NOT NULL
        RETURN count(lps) AS c
    """, _P(pid_id))

    if seeded_lps == 0:
        raise RuntimeError(
            f"[PHASE4] Flow assignment aborted — no LPS has flow_state for "
            f"pid_id={pid_id}. Run fsm_core.run_fsm() first."
        )

    # ── Assign from best ENDPOINT_OF LPS ──────────────────────────────────────
    # Only use LPS with a resolved direction (FORWARD/REVERSE).
    # UNKNOWN, SEEDED_UNKNOWN, BLOCKED, HITL_PENDING → not used as authority.
    updated = _scalar(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $equip_labels
          AND lps.flow_state IS NOT NULL
          AND lps.flow_direction IN ['FORWARD','REVERSE']
        WITH n, lps
        ORDER BY coalesce(toFloat(lps.flow_confidence), 0.0) DESC
        WITH n, collect(lps)[0] AS best
        SET n.flow_state      = best.flow_state,
            n.flow_direction  = best.flow_direction,
            n.flow_confidence = best.flow_confidence,
            n.flow_source     = 'phase4_equipment_assignment',
            n.flow_pid_id     = $pid_id
        RETURN count(DISTINCT n) AS c
    """, {**_P(pid_id), "equip_labels": EQUIPMENT_NODE_LABELS})

    logger.info("[PHASE4][FLOW_ASSIGN] Equipment nodes updated: %d", updated)

    # ── Nodes with no directional LPS available ────────────────────────────────
    unassigned = _scalar(session, """
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $equip_labels
          AND n.flow_state IS NULL
        RETURN count(DISTINCT n) AS c
    """, {**_P(pid_id), "equip_labels": EQUIPMENT_NODE_LABELS})

    if unassigned > 0:
        logger.warning(
            "[PHASE4][FLOW_ASSIGN] %d equipment nodes remain without flow_state "
            "(all connected LPS are UNKNOWN / SEEDED_UNKNOWN / BLOCKED / HITL_PENDING)",
            unassigned
        )

    # ── Direction distribution ─────────────────────────────────────────────────
    dist = session.run("""
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE n.label IN $equip_labels
        RETURN n.flow_direction AS dir,
               count(DISTINCT n)  AS n
        ORDER BY n DESC
    """, pid_id=pid_id, equip_labels=EQUIPMENT_NODE_LABELS).data()

    for r in dist:
        logger.info(
            "[PHASE4][FLOW_ASSIGN]   direction=%-10s  nodes=%d",
            r["dir"] or "None", int(r["n"])
        )

    # ── Integrity check: no equipment node received flow from a different PID ──
    # FIX-11: Check flow_pid_id instead of ENDPOINT_OF presence.
    contaminated = _scalar(session, """
        MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
        WHERE n.label IN $equip_labels
          AND n.flow_pid_id IS NOT NULL
          AND n.flow_pid_id <> $pid_id
        MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
        RETURN count(DISTINCT n) AS c
    """, {**_P(pid_id), "equip_labels": EQUIPMENT_NODE_LABELS})

    if contaminated > 0:
        logger.error(
            "[PHASE4][FLOW_ASSIGN] ❌ %d equipment nodes linked to foreign PID LPS",
            contaminated
        )

    # ── Phase 3.5: stamp engineering rule violation summary onto equipment nodes ─
    rule_violations_stamped = stamp_rule_violations_on_nodes(session, pid_id)

    return {
        "updated":                 updated,
        "unassigned":              unassigned,
        "seeded_lps":              seeded_lps,
        "contaminated":            contaminated,
        "rule_violations_stamped": rule_violations_stamped,
    }


# ── Phase 3.5 rule violation summary ─────────────────────────────────────────────

def stamp_rule_violations_on_nodes(session, pid_id: str) -> int:
    """
    Stamp Phase 3.5 engineering rule violation summaries onto equipment nodes.

    For each equipment node in this PID that has one or more
    engineering_rule_violation Annotations, writes:
      n.has_rule_violations  = true
      n.rule_violation_count = int   (total violations on this node)
      n.rule_violation_types = list  (distinct pattern_types)

    These properties are derived from Phase 3.5 Annotation nodes and are
    removed by clear_phase4_data on re-run.  The Annotation nodes themselves
    are Phase 3.5 data and are NOT touched by this function.

    Returns count of equipment nodes that received violation stamps.
    """
    violations_stamped = _scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})
        MATCH (a)-[:ANNOTATES]->(n:Node)
        WHERE n.label IN $equip_labels
        WITH n, collect(a) AS viols
        SET n.has_rule_violations  = true,
            n.rule_violation_count = size(viols),
            n.rule_violation_types = [v IN viols | v.pattern_type]
        RETURN count(DISTINCT n) AS c
    """, {**_P(pid_id), "equip_labels": EQUIPMENT_NODE_LABELS})

    if violations_stamped > 0:
        logger.info(
            "[PHASE4][FLOW_ASSIGN] Rule violation summary stamped on "
            "%d equipment nodes (Phase 3.5)",
            violations_stamped,
        )

    return violations_stamped