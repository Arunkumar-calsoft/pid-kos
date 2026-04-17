# engine/phase3_annotation/boundary_flow.py
#
# Phase 3 — Boundary flow evidence from inlet/outlet pennant nodes.
#
# R7 — Boundary pennant direction (annotate_boundary_flow)
#   inlet/outlet nodes are drawn as flag/pennant symbols at the drawing
#   boundary.  Their triangular tip direction, determined via the same
#   pixel-density analysis used for arrows in Phase 2, establishes
#   FORWARD or REVERSE direction relative to each connected LPS's spatial
#   segment vector.
#
# ORIENTATION-AGNOSTIC DESIGN:
#   No assumption about which edge (left/right/top/bottom) the node sits on.
#   No assumption about horizontal vs vertical orientation of the pennant.
#   Works identically for any drawing layout or symbol placement.
#
# ALGORITHM (per node):
#   1. Query Neo4j for the node bbox + connected LPS + that LPS's two
#      endpoint node centres.
#   2. Run detect_arrow_tip_direction() on the pennant bbox.
#      → pixel_direction: EAST / WEST / SOUTH / NORTH  (or None)
#   3. Convert pixel_direction to a signed 2-D arrow_vec:
#        EAST  → (+width,  0)
#        WEST  → (-width,  0)
#        SOUTH → (0,  +height)
#        NORTH → (0,  -height)
#   4. Build seg_vec from the LPS's two endpoint centres, spatially sorted
#      (Moon 2021 §3.1 — horizontal segment: left→right; vertical: top→down).
#      This is the same convention used by Phase 2 assign_flow_direction.py.
#   5. cosine(arrow_vec, seg_vec):
#        > +0.3 → FORWARD
#        < -0.3 → REVERSE
#        else   → UNKNOWN
#   6. Fallback when pixel analysis returns None:
#      Cannot determine direction from geometry alone — the vector from the
#      boundary node toward the interior is correct for INLETS (flow inward)
#      but INVERTED for OUTLETS (flow outward).  Since inlet vs outlet is
#      exactly what we are trying to determine, the fallback emits UNKNOWN
#      with confidence=0.0 so the FSM is unaffected, while the Evidence node
#      still prevents the LPS from being flagged as evidence-missing.
#
# INTEGRATION:
#   Called from run_phase3.py as Step 1.5, after _lift_flow_evidence (arrows)
#   and before equipment/check-valve annotation.  Uses the same Evidence node
#   + [:ABOUT]-> LPS pattern as all other Phase 3 sources.
#
# CONFIDENCE: 0.70 (structural inference — conservative, below explicit labels).
# SOURCE TAG:  'phase3_boundary_semantics'

import math
from collections import Counter, defaultdict
from typing import Dict, Optional, Tuple

from PIL import Image

from engine.phase2_flow.arrow_pixel_analysis import (
    arrow_cos_alignment,
    detect_arrow_tip_direction,
)

_BOUNDARY_LABEL    = "inlet/outlet"
_BASE_CONFIDENCE   = 0.70
_COSINE_THRESHOLD  = 0.3     # forward/reverse band — matches Phase 2

_PDIR_VEC: Dict[str, Tuple[float, float]] = {
    "EAST":  ( 1.0,  0.0),
    "WEST":  (-1.0,  0.0),
    "SOUTH": ( 0.0,  1.0),
    "NORTH": ( 0.0, -1.0),
}


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _centre(xmin, xmax, ymin, ymax) -> Tuple[float, float]:
    return (
        (_safe_float(xmin) + _safe_float(xmax)) / 2.0,
        (_safe_float(ymin) + _safe_float(ymax)) / 2.0,
    )


def _spatial_seg_vec(
    ep1: Tuple[float, float], ep2: Tuple[float, float]
) -> Tuple[float, float]:
    """
    Return a segment vector sorted left→right (H) or top→bottom (V),
    per Moon 2021 §3.1.  Matches the spatial_sort convention in Phase 2.
    """
    x1, y1 = ep1
    x2, y2 = ep2
    x_span = abs(x2 - x1)
    y_span = abs(y2 - y1)

    if x_span >= y_span:        # horizontal segment → left → right
        if x1 <= x2:
            return (x2 - x1, y2 - y1)
        return (x1 - x2, y1 - y2)
    else:                       # vertical segment → top → bottom
        if y1 <= y2:
            return (x2 - x1, y2 - y1)
        return (x1 - x2, y1 - y2)


def _scale_vec(d: str, width: float, height: float) -> Tuple[float, float]:
    """Scale a unit direction vector by the bbox dimensions."""
    ux, uy = _PDIR_VEC[d]
    dominant = width if abs(ux) > abs(uy) else height
    return (ux * dominant, uy * dominant)


def annotate_boundary_flow(
    session,
    pid_id: str,
    image_path: str,
) -> Tuple[int, Dict[str, Counter]]:
    """
    Create Evidence nodes (source='phase3_boundary_semantics') for every
    inlet/outlet node that can be directionally resolved.

    Returns:
        (annotated_count, direction_counts)
        where direction_counts maps lps_id → Counter({'FORWARD': n, ...})
        for downstream accumulation into the direction-frequency summary.

    Raises nothing — any per-node failure is logged and skipped.
    """
    annotated_count  = 0
    direction_counts: Dict[str, Counter] = defaultdict(Counter)

    # ── 1. Load PID image (grayscale) ─────────────────────────────────────
    pid_image: Optional[Image.Image] = None
    try:
        pid_image = Image.open(image_path).convert("L")
    except Exception as img_err:
        print(f"[PHASE3][R7] WARNING: cannot load PID image ({img_err}). "
              "Pixel tip detection disabled; geometric fallback will be used.")

    # ── 2. Query all inlet/outlet nodes + their connected LPS endpoints ───
    rows = session.run(
        """
        MATCH (n:Node {pid_id: $pid_id, label: $boundary_label})
        MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
        MATCH (ep:Node {pid_id: $pid_id})-[:ENDPOINT_OF]->(lps)
        WITH n, lps,
             collect(DISTINCT {
               id   : ep.id,
               xmin : ep.xmin, xmax : ep.xmax,
               ymin : ep.ymin, ymax : ep.ymax
             }) AS endpoints
        RETURN
            n.id   AS node_id,
            n.xmin AS xmin,  n.xmax AS xmax,
            n.ymin AS ymin,  n.ymax AS ymax,
            lps.id AS lps_id,
            endpoints
        ORDER BY n.id
        """,
        pid_id=pid_id,
        boundary_label=_BOUNDARY_LABEL,
    ).data()

    if not rows:
        print(f"[PHASE3][R7] No inlet/outlet nodes found for PID={pid_id}. Skipping.")
        return 0, direction_counts

    print(f"[PHASE3][R7] Processing {len(rows)} inlet/outlet node(s) for PID={pid_id}...")

    for row in rows:
        node_id = row.get("node_id")
        lps_id  = row.get("lps_id")
        if not node_id or not lps_id:
            continue

        xmin = _safe_float(row.get("xmin"))
        xmax = _safe_float(row.get("xmax"))
        ymin = _safe_float(row.get("ymin"))
        ymax = _safe_float(row.get("ymax"))
        width  = xmax - xmin
        height = ymax - ymin

        if width < 2.0 or height < 2.0:
            print(f"[PHASE3][R7] Skipping {node_id}: bbox too small ({width:.1f}x{height:.1f})")
            continue

        node_cx, node_cy = _centre(xmin, xmax, ymin, ymax)

        # ── 3. Build the LPS seg_vec from spatially-sorted endpoints ──────
        endpoints = row.get("endpoints") or []
        ep_centres = []
        for ep in endpoints:
            ex = _safe_float(ep.get("xmin"))
            ey = _safe_float(ep.get("ymin"))
            ex2 = _safe_float(ep.get("xmax"))
            ey2 = _safe_float(ep.get("ymax"))
            ep_centres.append(_centre(ex, ex2, ey, ey2))

        if len(ep_centres) < 2:
            # Degree-1 LPS (corner case) — cannot compute seg_vec from endpoints
            # Fall back to using just the vector from node to LPS endpoint
            if ep_centres:
                ecx, ecy = ep_centres[0]
                seg_vec = (ecx - node_cx, ecy - node_cy)
            else:
                print(f"[PHASE3][R7] Skipping {node_id}: no LPS endpoint centres.")
                continue
        else:
            ep1, ep2 = ep_centres[0], ep_centres[1]
            seg_vec = _spatial_seg_vec(ep1, ep2)

        seg_mag = math.hypot(seg_vec[0], seg_vec[1])
        if seg_mag < 1e-6:
            print(f"[PHASE3][R7] Skipping {node_id}: degenerate seg_vec.")
            continue

        # ── 4. Determine arrow_vec ─────────────────────────────────────────
        pixel_direction = None
        direction_method = "bbox_fallback"

        if pid_image is not None:
            try:
                pixel_direction = detect_arrow_tip_direction(
                    pid_image, xmin, ymin, xmax, ymax
                )
                if pixel_direction is not None:
                    direction_method = "pixel_tip"
            except Exception as pix_err:
                print(f"[PHASE3][R7] Pixel analysis failed for {node_id}: {pix_err}")

        if pixel_direction is not None:
            # Signed vector in the pixel-detected direction, scaled by bbox
            arrow_vec = _scale_vec(pixel_direction, width, height)
            confidence = _BASE_CONFIDENCE
            # ── 5. Cosine alignment → FORWARD / REVERSE / UNKNOWN ─────────
            try:
                alignment = float(arrow_cos_alignment(seg_vec, arrow_vec))
            except Exception:
                alignment = 0.0
            if alignment > _COSINE_THRESHOLD:
                direction_hint = "FORWARD"
            elif alignment < -_COSINE_THRESHOLD:
                direction_hint = "REVERSE"
            else:
                direction_hint = "UNKNOWN"
        else:
            # Pixel tip detection failed.
            # The vector from boundary-node → interior is correct for INLETS
            # but reversed for OUTLETS.  We cannot distinguish the two from
            # geometry alone without making PID-specific assumptions.
            # Emit UNKNOWN (confidence=0.0): the Evidence node still prevents
            # the LPS from being flagged as evidence-missing, but the FSM
            # weighted vote is not influenced in either direction.
            alignment      = 0.0
            direction_hint = "UNKNOWN"
            confidence     = 0.0

        # ── 6. Write Evidence node + [:ABOUT] relationship ─────────────────
        ev_id  = f"ev_boundary_{node_id}__{lps_id}"
        ann_id = f"ann_boundary_{pid_id}_{node_id}__{lps_id}"

        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id})
            MERGE (e:Evidence {id: $ev_id})
            ON CREATE SET
              e.pid_id             = $pid_id,
              e.source             = 'phase3_boundary_semantics',
              e.boundary_node_id   = $node_id,
              e.observed_direction = $direction,
              e.direction_hint     = $direction,
              e.confidence         = $confidence,
              e.cosine_alignment   = $cosine,
              e.pixel_direction    = $pixel_direction,
              e.direction_method   = $direction_method,
              e.low_confidence     = ($confidence < 0.5),
              e.first_seen         = datetime()
            ON MATCH SET
              e.confidence         = $confidence,
              e.cosine_alignment   = $cosine,
              e.last_seen          = datetime()
            MERGE (e)-[:ABOUT]->(lps)
            """,
            ev_id=ev_id, pid_id=pid_id, node_id=node_id, lps_id=lps_id,
            direction=direction_hint, confidence=confidence,
            cosine=round(alignment, 3),
            pixel_direction=pixel_direction,
            direction_method=direction_method,
        )
        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id}), (e:Evidence {id: $ev_id})
            MERGE (a:Annotation {id: $ann_id})
            ON CREATE SET
              a.pid_id             = $pid_id,
              a.type               = 'direction_observation',
              a.intent             = 'boundary_inference',
              a.source             = 'phase3_boundary_semantics',
              a.boundary_node_id   = $node_id,
              a.first_seen         = datetime()
            ON MATCH SET a.last_seen = datetime()
            MERGE (a)-[:ANNOTATES]->(lps)
            MERGE (a)-[:SUPPORTED_BY]->(e)
            """,
            ann_id=ann_id, ev_id=ev_id, pid_id=pid_id,
            node_id=node_id, lps_id=lps_id,
        )

        direction_counts[lps_id][direction_hint] += 1
        annotated_count += 1

        print(
            f"[PHASE3][R7] {node_id} → LPS={lps_id}  dir={direction_hint}"
            f"  cos={alignment:.3f}  method={direction_method}"
        )

    return annotated_count, direction_counts
