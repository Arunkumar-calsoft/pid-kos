# engine/phase2_flow/arrow_binding.py
#
# Bind arrow nodes to LogicalPipeSegments and generate preliminary flow evidence.
# Pure logic — no imports from engine packages, no DB access.
#
# DETERMINISM FIX:
#   Root cause of non-deterministic start/end assignment across runs:
#     1. `set(in_edges[aid] + out_edges[aid])` — set iteration order is
#        non-deterministic in CPython for string keys across runs.
#     2. `prefer_nodes(candidates)` — when two candidates share the same score,
#        their relative order in `scored` depends on input iteration order.
#     3. `fallback` distance sort — when two nodes are equidistant, their order
#        is undefined.
#   All three fixed by:
#     - Sorting candidate sets by node id before processing
#     - Adding node id as a secondary sort key in prefer_nodes and all distance sorts
#     - Using sorted() everywhere a set is converted to a list for indexing
#
# CANDIDATE_SEGS FIX:
#   Root cause: candidate_segs was built from node_to_seg[start_node] |
#   node_to_seg[end_node], where start_node and end_node are CONNECTOR nodes.
#   Phase 1 writes ENDPOINT_OF only for SYMBOL nodes (arrows, crossings, valves,
#   tanks, etc.), so node_to_seg maps symbol_ids → lps_ids. Connector ids are
#   never keys in node_to_seg → both lookups returned [] → candidate_segs was
#   always empty → the proximity fallback always fired, selecting the 3 nearest
#   LPS by symbol-center distance. This introduced junction-contaminated LPS
#   (LPS from adjacent crossing symbols that share connector nodes) into evidence,
#   producing UNKNOWN direction_hints for perpendicular LPS.
#   Fix: candidate_segs = set(node_to_seg.get(aid, [])) — the arrow IS a symbol,
#   so this lookup returns exactly the 1–2 LPS the arrow directly spans.
#   Expected result: FLOW_EVIDENCE = 82 (39×2 + 4×1), UNKNOWN = 0.

import math
from collections import defaultdict


def _node_centers(nodes):
    centers = {}
    for n in nodes:
        try:
            attrs = n.get("attrs", {})
            xmin  = float(attrs.get("xmin", 0))
            xmax  = float(attrs.get("xmax", xmin))
            ymin  = float(attrs.get("ymin", 0))
            ymax  = float(attrs.get("ymax", ymin))
            centers[n["id"]] = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        except Exception:
            continue
    return centers


def _is_arrow_node(node):
    label = (node.get("attrs", {}).get("label") or "").lower()
    return "arrow" in label


def bind_arrows_to_segments(nodes, edges, seg_map, symbol_dict=None):
    """
    Assign arrows to LogicalPipeSegments and generate preliminary evidence.

    Args:
        nodes:       list of node dicts
        edges:       list of edge dicts {src, dst}
        seg_map:     dict {lps_id → [node_ids]}  — LogicalPipeSegment endpoints
        symbol_dict: optional symbol dictionary for label preference scoring

    Returns:
        List of evidence dicts with keys:
            pipe_segment_id, arrow_id, direction_hint,
            start_node, end_node, dx, dy, source, extra_info
    """
    node_map  = {n["id"]: n for n in nodes}
    centers   = _node_centers(nodes)

    node_to_seg = defaultdict(list)
    for pid, nids in seg_map.items():
        for nid in nids:
            node_to_seg[nid].append(pid)

    in_edges  = defaultdict(list)
    out_edges = defaultdict(list)
    for e in edges:
        out_edges[e["src"]].append(e["dst"])
        in_edges[e["dst"]].append(e["src"])

    arrow_nodes = [n for n in nodes if _is_arrow_node(n)]

    # Sort all_centers once by node_id for deterministic distance tiebreaking
    all_centers = sorted(
        [(nid, centers[nid]) for nid in centers],
        key=lambda t: t[0],
    )

    def _arrow_tail_tip(arrow_attrs):
        """
        Derive the tail (upstream) and tip (downstream) points of an arrow
        from its bbox geometry.

        Convention: arrows are drawn so that the pointed end (tip) is the
        DOWNSTREAM end (flow direction).  The bbox encodes orientation:
          - W > H  → horizontal arrow.  Left edge = tail, right edge = tip.
          - H > W  → vertical arrow.    Top edge  = tail, bottom edge = tip.
          - square → ambiguous; fall back to center for both.

        Returns (tail_pt, tip_pt) as (x, y) tuples.
        """
        try:
            xmin = float(arrow_attrs.get("xmin", 0))
            xmax = float(arrow_attrs.get("xmax", xmin))
            ymin = float(arrow_attrs.get("ymin", 0))
            ymax = float(arrow_attrs.get("ymax", ymin))
        except (TypeError, ValueError):
            cx = cy = 0.0
            return (cx, cy), (cx, cy)

        w = xmax - xmin
        h = ymax - ymin
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0

        if w > h * 1.15:          # horizontal
            tail = (xmin, cy)
            tip  = (xmax, cy)
        elif h > w * 1.15:        # vertical
            tail = (cx, ymin)
            tip  = (cx, ymax)
        else:                      # square / ambiguous
            tail = (cx, cy)
            tip  = (cx, cy)

        return tail, tip

    def prefer_nodes(candidates, arrow_attrs=None):
        """
        Rank candidates — prefer connectors/equipment, exclude arrows.

        Tie-breaking strategy (in priority order):
          1. Label score: connector(10) > valve(8) > tank/pump(6) > other(0)
          2. Geometric proximity to arrow bbox endpoints — the candidate
             closest to the tail end becomes start_node; closest to tip
             becomes end_node.  This uses actual geometry, not node ID strings,
             so the ordering reflects physical layout rather than naming convention.
          3. Node ID (ascending) as final lexicographic tiebreaker to guarantee
             full determinism when two nodes are at identical distances.

        Returns list ordered [best_start_candidate, best_end_candidate, ...].
        Callers take [0] as start_node and [1] as end_node.
        """
        scored = []
        for nid in candidates:
            node = node_map.get(nid)
            if not node or _is_arrow_node(node):
                continue
            label = (node.get("attrs", {}).get("label") or "").lower()
            score = 0
            if "connector" in label:
                score += 10
            elif "valve" in label:
                score += 8
            elif "tank" in label or "pump" in label:
                score += 6
            scored.append((score, nid))

        if not scored:
            return []

        # Sort by score descending first to find the top-score tier
        scored.sort(key=lambda x: -x[0])
        top_score = scored[0][0]
        top_tier  = [nid for s, nid in scored if s == top_score]

        if len(top_tier) <= 1:
            # No tie at top — deterministic already; keep full scored order
            # with node_id as secondary for lower tiers
            scored.sort(key=lambda x: (-x[0], x[1]))
            return [nid for _, nid in scored]

        # Tie at top tier — break geometrically using arrow tail/tip.
        # Initialise tail/tip to sentinel values so they are always bound
        # regardless of whether arrow_attrs is truthy.
        tail: tuple = (0.0, 0.0)
        tip:  tuple = (0.0, 0.0)
        ambiguous = True

        if arrow_attrs:
            tail, tip = _arrow_tail_tip(arrow_attrs)
            ambiguous = (tail == tip)   # square bbox: geometry is uninformative

        if not ambiguous:
            # Among top-tier nodes, assign the one closest to tail as start,
            # closest to tip as end.  Distance ties broken by node_id.
            def _dist_to(pt, nid):
                c = centers.get(nid)
                if c is None:
                    return (float("inf"), nid)
                return (math.hypot(c[0] - pt[0], c[1] - pt[1]), nid)

            top_tier_sorted_by_tail = sorted(top_tier, key=lambda n: _dist_to(tail, n))
            top_tier_sorted_by_tip  = sorted(top_tier, key=lambda n: _dist_to(tip,  n))

            start_candidate = top_tier_sorted_by_tail[0]
            # end candidate: closest to tip that is NOT the start candidate
            end_candidates = [n for n in top_tier_sorted_by_tip if n != start_candidate]
            end_candidate  = end_candidates[0] if end_candidates else (
                top_tier_sorted_by_tip[0] if top_tier_sorted_by_tip else start_candidate
            )

            # Build final list: [start, end] first, then remaining top-tier
            # by node_id, then lower-scored nodes by (score desc, node_id asc)
            remaining_top = sorted(
                n for n in top_tier if n not in (start_candidate, end_candidate)
            )
            lower = sorted(
                (s, n) for s, n in scored if s < top_score
            )
            ordered = (
                [start_candidate, end_candidate]
                + remaining_top
                + [n for _, n in lower]
            )
            return ordered
        else:
            # Ambiguous geometry — fall back to node_id sort (stable, deterministic)
            scored.sort(key=lambda x: (-x[0], x[1]))
            return [nid for _, nid in scored]

    evidence = []

    for arrow in arrow_nodes:
        aid = arrow["id"]

        # Deterministic: sorted list, not raw set
        raw_connected = list(set(in_edges[aid] + out_edges[aid]))
        raw_connected.sort()
        connected = raw_connected

        candidates = sorted(
            n for n in connected
            if not (n in node_map and _is_arrow_node(node_map[n]))
        )

        # Compute arrow bbox attrs once for geometry-aware tie-breaking
        a_attrs = arrow.get("attrs", {}) or {}
        try:
            arrow_center = (
                (float(a_attrs["xmin"]) + float(a_attrs["xmax"])) / 2.0,
                (float(a_attrs["ymin"]) + float(a_attrs["ymax"])) / 2.0,
            )
        except Exception:
            arrow_center = (0.0, 0.0)

        # Fallback: nearest non-arrow nodes if no connected candidates
        if not candidates:
            dlist = []
            for nid, c in all_centers:
                node = node_map.get(nid)
                if node and _is_arrow_node(node):
                    continue
                dx = arrow_center[0] - c[0]
                dy = arrow_center[1] - c[1]
                dlist.append((math.hypot(dx, dy), nid))
            dlist.sort(key=lambda x: (x[0], x[1]))
            for _, nid in dlist[:6]:
                candidates.append(nid)

        if not candidates:
            continue

        preferred = prefer_nodes(candidates, arrow_attrs=a_attrs)
        if not preferred:
            preferred = sorted(candidates)

        start_node = preferred[0]
        end_node   = preferred[1] if len(preferred) > 1 else None

        if end_node is None:
            fallback = [
                (math.hypot(arrow_center[0] - c[0], arrow_center[1] - c[1]), nid)
                for nid, c in all_centers
                if nid != start_node
                and not (node_map.get(nid) and _is_arrow_node(node_map[nid]))
            ]
            fallback.sort(key=lambda x: (x[0], x[1]))
            end_node = fallback[0][1] if fallback else start_node

        # dx, dy from start → end
        c1 = centers.get(start_node)
        c2 = centers.get(end_node)
        dx = (c2[0] - c1[0]) if (c1 and c2) else 0.0
        dy = (c2[1] - c1[1]) if (c1 and c2) else 0.0

        # Candidate segments — use arrow symbol's own LPS membership.
        #
        # Architecture: Phase 1 writes ENDPOINT_OF for the two SYMBOL nodes
        # that bound each LogicalPipeSegment. seg_map therefore contains
        # {lps_id: [symbol_id, symbol_id]}, and node_to_seg maps symbol_ids
        # back to lps_ids. Arrow nodes ARE symbols, so node_to_seg[aid] returns
        # exactly the 1–2 LPS this arrow directly spans — no more, no less.
        #
        # Previous code looked up start_node / end_node (connector IDs) in
        # node_to_seg. Connectors are NOT symbols, so that lookup always
        # returned [] → candidate_segs was always empty → the proximity
        # fallback always fired → each arrow picked up 2–3 LPS by distance,
        # including junction-contaminated LPS from adjacent crossing symbols.
        # The contaminated items produced cosine ≈ 0 → UNKNOWN direction_hint.
        #
        # With the direct lookup: 39 arrows → 2 LPS each, 4 arrows → 1 LPS each.
        # Expected FLOW_EVIDENCE total = 82. UNKNOWN=0 (no more contamination).
        candidate_segs = set(node_to_seg.get(aid, []))

        # Safety-net fallback: only reached when the arrow has NO LPS in the DB
        # (i.e., Phase 1 did not create any LogicalPipeSegment for this arrow).
        # In normal operation this should never fire — every arrow symbol is
        # an endpoint of at least one LPS after Phase 1 completes successfully.
        # If it does fire, log a warning so the data gap is visible.
        if not candidate_segs:
            import warnings
            warnings.warn(
                f"[arrow_binding] No LPS found for arrow '{aid}' — "
                "Phase 1 may not have created LogicalPipeSegments for this arrow. "
                "Falling back to proximity-based segment selection.",
                stacklevel=2,
            )
            seg_dist = []
            for nid, segs in node_to_seg.items():
                node = node_map.get(nid)
                if node and _is_arrow_node(node):
                    continue
                c = centers.get(nid)
                if c:
                    d = math.hypot(arrow_center[0] - c[0], arrow_center[1] - c[1])
                    for s in segs:
                        # FIX 5: secondary sort by (distance, seg_id) for ties
                        seg_dist.append((d, s))
            seg_dist.sort(key=lambda x: (x[0], x[1]))
            for _, s in seg_dist[:3]:
                candidate_segs.add(s)

        filtered = bool(connected and len(connected) != len(candidates))
        for seg_id in candidate_segs:
            evidence.append({
                "pipe_segment_id": seg_id,
                "arrow_id":        aid,
                "direction_hint":  "UNKNOWN",
                "start_node":      start_node,
                "end_node":        end_node,
                "dx":              dx,
                "dy":              dy,
                "source":          "arrow_binding",
                "extra_info":      {"filtered_arrow_neighbors": filtered},
            })

    return evidence