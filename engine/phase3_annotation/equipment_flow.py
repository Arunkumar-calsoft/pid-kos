# engine/phase3_annotation/equipment_flow.py
#
# Phase 3 — Equipment-based and check-valve-based flow evidence.
#
# TWO SOURCES (R4 + R6) + ONE NEO4J-SOURCED SOURCE (R6b):
#
# R4 — Equipment outlet/inlet semantics (annotate_equipment_flow)
#   Pumps, compressors, ejectors: outlet identified from bbox geometry.
#   Confidence: 0.80.
#
# R6 — Check valve directional annotation (annotate_check_valve_flow)
#   Explicit check_valve/nrv/non_return/check label nodes from raw GraphML.
#   Direction from bbox aspect ratio. Confidence: 0.85.
#
# R6b — Inferred check valve annotation (annotate_inferred_check_valve_flow)
#   NEW-B FIX: Phase 1 classify_equipment.py relabels 'general' float-coord
#   degree-2 nodes to 'inferred_check_valve' in Neo4j, but this label change
#   is NOT reflected in the raw `nodes` list passed to R4/R6 (which comes from
#   parse_graphml).  This function queries Neo4j directly for nodes with
#   label='inferred_check_valve' and generates R6-equivalent evidence for them.
#   Confidence: 0.70 (lower than explicit labels — label was inferred).
#
# TAXONOMY SOURCE:
#   EQUIPMENT_LABELS and CHECK_VALVE_LABELS are derived from
#   engine.domain_knowledge.symbol_dictionary for a single source of truth.
#   TANK EXCEPTION: small 'tank' nodes (width < 100px) are condensate pump
#   symbols — injected manually with bbox_width_max=100.0.

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from engine.domain_knowledge.symbol_dictionary import (
    get_equipment_flow_labels as _get_equipment_flow_labels,
    get_check_valve_labels    as _get_check_valve_labels,
)


# ── Equipment taxonomy ─────────────────────────────────────────────────────────

EQUIPMENT_LABELS: Dict[str, Dict[str, Any]] = {
    **_get_equipment_flow_labels(),
    # TANK EXCEPTION: small tank symbols = condensate pump units (CND-PU-xxx).
    "tank": {"confidence": 0.70, "category": "active", "bbox_width_max": 100.0},
}

# Covers check_valve, nrv, non_return_valve, non_return, check,
# and inferred_check_valve (all have function='backflow_prevention' in symbol_dictionary).
CHECK_VALVE_LABELS: Dict[str, float] = _get_check_valve_labels()

_MIN_AXIS_SEPARATION = 5.0   # pixels


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _bbox_center(attrs: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    xmin = attrs.get("xmin")
    xmax = attrs.get("xmax")
    ymin = attrs.get("ymin")
    ymax = attrs.get("ymax")
    if any(v is None for v in (xmin, xmax, ymin, ymax)):
        return None
    return (
        (_safe_float(xmin) + _safe_float(xmax)) / 2.0,
        (_safe_float(ymin) + _safe_float(ymax)) / 2.0,
    )


def _dominant_axis(cx: float, cy: float, candidates: List[Tuple[str, float, float]]) -> str:
    if not candidates:
        return "H"
    total_dx = sum(abs(x - cx) for _, x, y in candidates)
    total_dy = sum(abs(y - cy) for _, x, y in candidates)
    return "H" if total_dx >= total_dy else "V"


def _identify_outlet(
    eq_center: Tuple[float, float],
    lps_endpoints: List[Tuple[str, float, float]],
    axis: str,
) -> Optional[Tuple[str, Optional[str]]]:
    if len(lps_endpoints) < 2:
        return None

    cx, cy = eq_center

    if axis == "H":
        scored = [(abs(x - cx), lps_id, x > cx) for lps_id, x, y in lps_endpoints]
    else:
        scored = [(abs(y - cy), lps_id, y < cy) for lps_id, x, y in lps_endpoints]

    scored.sort(key=lambda t: -t[0])

    if len(scored) >= 2 and abs(scored[0][0] - scored[1][0]) < _MIN_AXIS_SEPARATION:
        return None

    outlet_lps = scored[0][1]
    inlet_lps  = scored[1][1] if len(scored) >= 2 else None
    return outlet_lps, inlet_lps


# ── R4: Equipment-based flow evidence ─────────────────────────────────────────

def annotate_equipment_flow(session, pid_id: str, nodes: List[Dict[str, Any]]) -> int:
    """
    For each pump/compressor/ejector/small-tank node in this PID:
    identify outlet from bbox geometry, write FORWARD Evidence on outlet LPS
    and REVERSE Evidence on inlet LPS.
    """
    node_index = {n["id"]: n for n in nodes if isinstance(n, dict)}
    written    = 0

    equipment_nodes = [
        n for n in nodes
        if isinstance(n, dict)
        and any(
            alias == (n.get("attrs", {}).get("label") or "").lower()
            for alias in EQUIPMENT_LABELS
        )
    ]

    for eq_node in equipment_nodes:
        eq_id    = eq_node["id"]
        eq_attrs = eq_node.get("attrs", {})
        eq_label = (eq_attrs.get("label") or "").lower()
        eq_cfg   = next(
            (cfg for alias, cfg in EQUIPMENT_LABELS.items() if alias in eq_label),
            None,
        )
        if eq_cfg is None:
            continue

        bbox_width_max = eq_cfg.get("bbox_width_max")
        if bbox_width_max is not None:
            bbox_w = _safe_float(eq_attrs.get("xmax")) - _safe_float(eq_attrs.get("xmin"))
            if bbox_w > bbox_width_max:
                continue

        confidence = eq_cfg["confidence"]
        eq_center  = _bbox_center(eq_attrs)
        if not eq_center:
            continue

        rows = session.run(
            """
            MATCH (n:Node {id: $nid})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
            RETURN lps.id AS lps_id, lps.endpoints AS endpoints
            """,
            nid=eq_id, pid_id=pid_id,
        ).data()

        if not rows:
            continue

        lps_endpoints: List[Tuple[str, float, float]] = []
        for r in rows:
            lps_id = r["lps_id"]
            ep_rows = session.run(
                """
                MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {id: $lps_id})
                WHERE n.id <> $eq_id
                RETURN n.id AS nid, n.xmin AS xmin, n.xmax AS xmax,
                       n.ymin AS ymin, n.ymax AS ymax
                LIMIT 1
                """,
                lps_id=lps_id, eq_id=eq_id,
            ).data()
            if not ep_rows:
                lps_endpoints.append((lps_id, eq_center[0], eq_center[1]))
                continue
            ep = ep_rows[0]
            cx = (_safe_float(ep.get("xmin")) + _safe_float(ep.get("xmax"))) / 2.0
            cy = (_safe_float(ep.get("ymin")) + _safe_float(ep.get("ymax"))) / 2.0
            lps_endpoints.append((lps_id, cx, cy))

        if not lps_endpoints:
            continue

        axis   = _dominant_axis(eq_center[0], eq_center[1], lps_endpoints)
        result = _identify_outlet(eq_center, lps_endpoints, axis)

        if result is None:
            for lps_id, _, _ in lps_endpoints:
                _write_equipment_evidence(
                    session, pid_id, eq_id, eq_label, lps_id,
                    direction="UNKNOWN", confidence=confidence * 0.5,
                    axis=axis, role="ambiguous",
                )
            continue

        outlet_lps, inlet_lps = result
        _write_equipment_evidence(
            session, pid_id, eq_id, eq_label, outlet_lps,
            direction="FORWARD", confidence=confidence, axis=axis, role="outlet",
        )
        if inlet_lps:
            _write_equipment_evidence(
                session, pid_id, eq_id, eq_label, inlet_lps,
                direction="REVERSE", confidence=confidence, axis=axis, role="inlet",
            )
        written += 1

    print(
        f"[PHASE3][EQUIPMENT] Equipment flow evidence written for "
        f"{written}/{len(equipment_nodes)} equipment nodes | PID={pid_id}"
    )
    return written


def _write_equipment_evidence(
    session, pid_id: str, eq_id: str, eq_label: str,
    lps_id: str, direction: str, confidence: float,
    axis: str, role: str,
) -> None:
    ev_id  = f"ev_eq_{eq_id}__{lps_id}"
    ann_id = f"ann_eq_{pid_id}_{eq_id}__{lps_id}"

    session.run(
        """
        MATCH (lps:LogicalPipeSegment {id: $lps_id})
        MERGE (e:Evidence {id: $ev_id})
        ON CREATE SET
          e.pid_id             = $pid_id,
          e.source             = 'phase3_equipment_semantics',
          e.equipment_id       = $eq_id,
          e.equipment_label    = $eq_label,
          e.observed_direction = $direction,
          e.direction_hint     = $direction,
          e.confidence         = $confidence,
          e.axis               = $axis,
          e.role               = $role,
          e.low_confidence     = ($confidence < 0.5),
          e.first_seen         = datetime()
        ON MATCH SET e.last_seen = datetime()
        MERGE (e)-[:ABOUT]->(lps)
        """,
        ev_id=ev_id, pid_id=pid_id, eq_id=eq_id, eq_label=eq_label,
        lps_id=lps_id, direction=direction, confidence=confidence,
        axis=axis, role=role,
    )
    session.run(
        """
        MATCH (lps:LogicalPipeSegment {id: $lps_id}), (e:Evidence {id: $ev_id})
        MERGE (a:Annotation {id: $ann_id})
        ON CREATE SET
          a.pid_id        = $pid_id,
          a.type          = 'direction_observation',
          a.intent        = 'equipment_semantics',
          a.source        = 'phase3_equipment_semantics',
          a.equipment_id  = $eq_id,
          a.role          = $role,
          a.first_seen    = datetime()
        ON MATCH SET a.last_seen = datetime()
        MERGE (a)-[:ANNOTATES]->(lps)
        MERGE (a)-[:SUPPORTED_BY]->(e)
        """,
        ann_id=ann_id, ev_id=ev_id, pid_id=pid_id,
        lps_id=lps_id, eq_id=eq_id, role=role,
    )


# ── R6: Check valve directional annotation (explicit labels) ───────────────────

def annotate_check_valve_flow(
    session, pid_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
) -> int:
    """
    For each check valve / NRV node in this PID (from raw GraphML nodes list):
    determine pipe axis from bbox aspect ratio, write FORWARD Evidence on
    downstream LPS and REVERSE Evidence on upstream LPS.

    Covers: check_valve, nrv, non_return_valve, non_return, check.
    Does NOT cover 'inferred_check_valve' nodes — those are written by
    annotate_inferred_check_valve_flow which queries Neo4j directly.
    """
    node_index = {n["id"]: n for n in nodes if isinstance(n, dict)}
    written    = 0

    # Exclude inferred_check_valve here — handled by R6b below.
    explicit_labels = {k: v for k, v in CHECK_VALVE_LABELS.items()
                       if k != "inferred_check_valve"}

    check_nodes = [
        n for n in nodes
        if isinstance(n, dict)
        and any(
            alias == (n.get("attrs", {}).get("label") or "").lower()
            for alias in explicit_labels
        )
    ]

    neighbors: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if not isinstance(e, dict):
            continue
        src, dst = e.get("src"), e.get("dst")
        if src and dst:
            neighbors[src].append(dst)
            neighbors[dst].append(src)

    for cv_node in check_nodes:
        cv_id    = cv_node["id"]
        cv_attrs = cv_node.get("attrs", {})
        cv_label = (cv_attrs.get("label") or "").lower()
        confidence = next(
            (conf for alias, conf in explicit_labels.items() if alias in cv_label),
            0.80,
        )

        cv_center = _bbox_center(cv_attrs)
        if not cv_center:
            continue

        bbox_w = _safe_float(cv_attrs.get("xmax")) - _safe_float(cv_attrs.get("xmin"))
        bbox_h = _safe_float(cv_attrs.get("ymax")) - _safe_float(cv_attrs.get("ymin"))
        ratio  = (bbox_w / bbox_h) if bbox_h > 0 else 1.0

        if ratio > 1.15:
            axis = "H"
        elif ratio < 0.85:
            axis = "V"
        else:
            nb_ids = neighbors.get(cv_id, [])
            total_h = total_v = 0.0
            for nb_id in nb_ids:
                nb_node = node_index.get(nb_id)
                if not nb_node:
                    continue
                nb_center = _bbox_center(nb_node.get("attrs", {}))
                if not nb_center:
                    continue
                total_h += abs(nb_center[0] - cv_center[0])
                total_v += abs(nb_center[1] - cv_center[1])
            if total_h == 0 and total_v == 0:
                axis = None
            else:
                axis = "H" if total_h >= total_v else "V"

        rows = session.run(
            "MATCH (n:Node {id: $nid})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id}) RETURN lps.id AS lps_id",
            nid=cv_id, pid_id=pid_id,
        ).data()

        lps_ids = [r["lps_id"] for r in rows]
        if not lps_ids:
            continue

        if axis is None or len(lps_ids) < 2:
            for lps_id in lps_ids:
                _write_check_valve_evidence(
                    session, pid_id, cv_id, cv_label, lps_id,
                    direction="UNKNOWN", confidence=confidence * 0.4,
                    axis="UNKNOWN", role="check_valve_ambiguous",
                )
            continue

        lps_scored: List[Tuple[float, str]] = []
        for lps_id in lps_ids:
            ep_rows = session.run(
                """
                MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {id: $lps_id})
                WHERE n.id <> $cv_id
                RETURN n.xmin AS xmin, n.xmax AS xmax, n.ymin AS ymin, n.ymax AS ymax
                LIMIT 1
                """,
                lps_id=lps_id, cv_id=cv_id,
            ).data()
            if not ep_rows:
                lps_scored.append((0.0, lps_id))
                continue
            ep = ep_rows[0]
            cx = (_safe_float(ep.get("xmin")) + _safe_float(ep.get("xmax"))) / 2.0
            cy = (_safe_float(ep.get("ymin")) + _safe_float(ep.get("ymax"))) / 2.0
            score = cx if axis == "H" else -cy
            lps_scored.append((score, lps_id))

        lps_scored.sort(key=lambda t: -t[0])
        downstream_lps = lps_scored[0][1]
        upstream_lps   = lps_scored[-1][1] if len(lps_scored) >= 2 else None

        _write_check_valve_evidence(
            session, pid_id, cv_id, cv_label, downstream_lps,
            direction="FORWARD", confidence=confidence, axis=axis, role="downstream",
        )
        if upstream_lps and upstream_lps != downstream_lps:
            _write_check_valve_evidence(
                session, pid_id, cv_id, cv_label, upstream_lps,
                direction="REVERSE", confidence=confidence, axis=axis, role="upstream",
            )
        written += 1

    print(
        f"[PHASE3][CHECK_VALVE] Check valve flow evidence written for "
        f"{written}/{len(check_nodes)} explicit check valve nodes | PID={pid_id}"
    )
    return written


def _write_check_valve_evidence(
    session, pid_id: str, cv_id: str, cv_label: str,
    lps_id: str, direction: str, confidence: float,
    axis: str, role: str,
) -> None:
    ev_id  = f"ev_cv_{cv_id}__{lps_id}"
    ann_id = f"ann_cv_{pid_id}_{cv_id}__{lps_id}"

    session.run(
        """
        MATCH (lps:LogicalPipeSegment {id: $lps_id})
        MERGE (e:Evidence {id: $ev_id})
        ON CREATE SET
          e.pid_id             = $pid_id,
          e.source             = 'phase3_check_valve',
          e.valve_id           = $cv_id,
          e.valve_label        = $cv_label,
          e.observed_direction = $direction,
          e.direction_hint     = $direction,
          e.confidence         = $confidence,
          e.axis               = $axis,
          e.role               = $role,
          e.low_confidence     = ($confidence < 0.5),
          e.first_seen         = datetime()
        ON MATCH SET e.last_seen = datetime()
        MERGE (e)-[:ABOUT]->(lps)
        """,
        ev_id=ev_id, pid_id=pid_id, cv_id=cv_id, cv_label=cv_label,
        lps_id=lps_id, direction=direction, confidence=confidence,
        axis=axis, role=role,
    )
    session.run(
        """
        MATCH (lps:LogicalPipeSegment {id: $lps_id}), (e:Evidence {id: $ev_id})
        MERGE (a:Annotation {id: $ann_id})
        ON CREATE SET
          a.pid_id       = $pid_id,
          a.type         = 'direction_observation',
          a.intent       = 'check_valve_semantics',
          a.source       = 'phase3_check_valve',
          a.valve_id     = $cv_id,
          a.role         = $role,
          a.first_seen   = datetime()
        ON MATCH SET a.last_seen = datetime()
        MERGE (a)-[:ANNOTATES]->(lps)
        MERGE (a)-[:SUPPORTED_BY]->(e)
        """,
        ann_id=ann_id, ev_id=ev_id, pid_id=pid_id,
        lps_id=lps_id, cv_id=cv_id, role=role,
    )


# ── R6b: Inferred check valve annotation (NEW-B) ──────────────────────────────

def annotate_inferred_check_valve_flow(session, pid_id: str) -> int:
    """
    NEW-B: Generate R6-equivalent flow evidence for 'inferred_check_valve' nodes.

    WHY THIS FUNCTION EXISTS:
      Phase 1 classify_equipment.py relabels small float-coord degree-2 'general'
      nodes to 'inferred_check_valve' in Neo4j.  However, the `nodes` list passed
      to annotate_check_valve_flow is the raw output of parse_graphml + normalize_nodes,
      where labels are still 'general'.  annotate_check_valve_flow therefore never
      sees these nodes and produces no evidence for them.

      This function queries Neo4j directly for nodes with label='inferred_check_valve',
      then uses their connected LPS geometry (from ENDPOINT_OF) to assign direction.
      The same axis-scoring logic is used as in R6.

    Confidence: 0.70 (lower than explicit labels — the label was inferred).

    Returns: count of inferred_check_valve nodes that produced directional evidence.
    """
    _INFERRED_CV_CONFIDENCE = 0.70

    # Fetch all inferred_check_valve nodes in this PID with their bbox
    cv_rows = session.run(
        """
        MATCH (n:Node {pid_id: $pid_id, label: 'inferred_check_valve'})
        RETURN n.id   AS nid,
               n.xmin AS xmin, n.xmax AS xmax,
               n.ymin AS ymin, n.ymax AS ymax
        """,
        pid_id=pid_id,
    ).data()

    if not cv_rows:
        print(f"[PHASE3][CHECK_VALVE] No inferred_check_valve nodes in PID={pid_id}")
        return 0

    written = 0

    for r in cv_rows:
        cv_id     = r["nid"]
        xmin, xmax = _safe_float(r["xmin"]), _safe_float(r["xmax"])
        ymin, ymax = _safe_float(r["ymin"]), _safe_float(r["ymax"])
        bbox_w    = xmax - xmin
        bbox_h    = ymax - ymin
        ratio     = (bbox_w / bbox_h) if bbox_h > 0 else 1.0

        # Determine axis from bbox
        if ratio > 1.15:
            axis = "H"
        elif ratio < 0.85:
            axis = "V"
        else:
            # Square — use neighbor positions from Neo4j as tiebreaker
            nb_rows = session.run(
                """
                MATCH (cv:Node {id: $cv_id})-[:PIPE]-(nb:Node {pid_id: $pid_id})
                RETURN nb.xmin AS xmin, nb.xmax AS xmax, nb.ymin AS ymin, nb.ymax AS ymax
                """,
                cv_id=cv_id, pid_id=pid_id,
            ).data()
            cv_cx = (xmin + xmax) / 2.0
            cv_cy = (ymin + ymax) / 2.0
            total_h = total_v = 0.0
            for nb in nb_rows:
                nb_cx = (_safe_float(nb.get("xmin")) + _safe_float(nb.get("xmax"))) / 2.0
                nb_cy = (_safe_float(nb.get("ymin")) + _safe_float(nb.get("ymax"))) / 2.0
                total_h += abs(nb_cx - cv_cx)
                total_v += abs(nb_cy - cv_cy)
            if total_h == 0 and total_v == 0:
                axis = None
            else:
                axis = "H" if total_h >= total_v else "V"

        # Find connected LPS
        lps_rows = session.run(
            "MATCH (n:Node {id: $nid})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id}) RETURN lps.id AS lps_id",
            nid=cv_id, pid_id=pid_id,
        ).data()

        lps_ids = [r2["lps_id"] for r2 in lps_rows]
        if not lps_ids:
            continue

        if axis is None or len(lps_ids) < 2:
            for lps_id in lps_ids:
                _write_check_valve_evidence(
                    session, pid_id, cv_id, "inferred_check_valve", lps_id,
                    direction="UNKNOWN", confidence=_INFERRED_CV_CONFIDENCE * 0.4,
                    axis="UNKNOWN", role="inferred_cv_ambiguous",
                )
            continue

        # Score LPS by forward direction (same as R6)
        lps_scored: List[Tuple[float, str]] = []
        for lps_id in lps_ids:
            ep_rows = session.run(
                """
                MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {id: $lps_id})
                WHERE n.id <> $cv_id
                RETURN n.xmin AS xmin, n.xmax AS xmax, n.ymin AS ymin, n.ymax AS ymax
                LIMIT 1
                """,
                lps_id=lps_id, cv_id=cv_id,
            ).data()
            if not ep_rows:
                lps_scored.append((0.0, lps_id))
                continue
            ep  = ep_rows[0]
            ecx = (_safe_float(ep.get("xmin")) + _safe_float(ep.get("xmax"))) / 2.0
            ecy = (_safe_float(ep.get("ymin")) + _safe_float(ep.get("ymax"))) / 2.0
            score = ecx if axis == "H" else -ecy
            lps_scored.append((score, lps_id))

        lps_scored.sort(key=lambda t: -t[0])
        downstream_lps = lps_scored[0][1]
        upstream_lps   = lps_scored[-1][1] if len(lps_scored) >= 2 else None

        _write_check_valve_evidence(
            session, pid_id, cv_id, "inferred_check_valve", downstream_lps,
            direction="FORWARD", confidence=_INFERRED_CV_CONFIDENCE,
            axis=axis, role="downstream",
        )
        if upstream_lps and upstream_lps != downstream_lps:
            _write_check_valve_evidence(
                session, pid_id, cv_id, "inferred_check_valve", upstream_lps,
                direction="REVERSE", confidence=_INFERRED_CV_CONFIDENCE,
                axis=axis, role="upstream",
            )
        written += 1

    print(
        f"[PHASE3][CHECK_VALVE] Inferred check valve flow evidence written for "
        f"{written}/{len(cv_rows)} inferred_check_valve nodes | PID={pid_id}"
    )
    return written