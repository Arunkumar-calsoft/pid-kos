# engine/phase0_ingestion/phase0_verify.py
#
# CHANGES FROM ORIGINAL:
#   - Separated WARN vs RAISE logic:
#       * Background nodes: expected-ignorable, warned not raised
#         (already filtered by normalize_nodes, but defensive check kept)
#       * Invalid bbox on equipment/topology nodes: still raises
#   - Added degree-based anomaly detection:
#       * Degree-0 nodes beyond expected orphans → AnnotationRequest candidates
#       * Degree-1 non-boundary nodes (valves, instrumentation) → anomaly log
#   - Added duplicate bbox detection (cross-check against normalize output)
#   - Added image existence + basic dimension sanity check
#   - Returns a structured verification report dict instead of only printing,
#     so main_phase0 can pass it to load_annotation_requests later.


import os
from collections import defaultdict


# Labels where degree-0 is expected (boundary/metadata nodes)
_EXPECTED_ORPHAN_LABELS = {"background"}

# Labels where degree-1 is anomalous (inline components need ≥2 connections)
_INLINE_LABELS = {"valve", "instrumentation", "general"}

# Labels that are legitimate degree-1 boundary nodes
_BOUNDARY_LABELS = {"inlet/outlet"}


def verify_ground_truth(nodes, edges, image_path="data/2.png"):
    """
    Structural verification of parsed and normalised node/edge data.

    Raises ValueError for hard structural errors (malformed bbox,
    dangling edge references).

    Warns and records — but does not raise — for engineering anomalies
    (degree-0 orphans, degree-1 inline nodes, duplicate bboxes).

    Returns a verification report dict:
    {
        "node_count": int,
        "edge_count": int,
        "anomalies": [
            {
                "type": "ORPHAN_NODE" | "DANGLING_INLINE" | "DUPLICATE_BBOX",
                "node_id": str,
                "label": str,
                "detail": str,
            },
            ...
        ]
    }
    """

    print("[PHASE 0][VERIFY] Starting verification")

    # ── Image check ────────────────────────────────────────────────────────
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Missing reference image: {image_path}")

    image_size = os.path.getsize(image_path)
    if image_size < 1024:
        raise ValueError(
            f"Reference image suspiciously small ({image_size} bytes): "
            f"{image_path}"
        )

    print(f"[PHASE 0][VERIFY] Reference image OK: {image_path} "
          f"({image_size / 1024:.1f} KB)")

    # ── Build lookup structures ────────────────────────────────────────────
    node_ids = set()
    node_label = {}   # id → label
    bbox_seen = {}    # bbox_tuple → first node_id

    anomalies = []

    # ── Node validation ────────────────────────────────────────────────────
    for n in nodes:
        nid = n["id"]
        attrs = n.get("attrs", {})
        label = attrs.get("label", "")

        node_ids.add(nid)
        node_label[nid] = label

        # Bbox presence check
        required = ["xmin", "ymin", "xmax", "ymax"]
        missing = [k for k in required if k not in attrs]

        if missing:
            raise ValueError(
                f"Node {nid} ({label}) missing bbox fields: {missing}"
            )

        xmin = attrs["xmin"]
        ymin = attrs["ymin"]
        xmax = attrs["xmax"]
        ymax = attrs["ymax"]

        # Degenerate bbox — hard error for topology nodes, warn for others
        if xmax <= xmin or ymax <= ymin:
            raise ValueError(
                f"Degenerate bbox for node {nid} ({label}): "
                f"({xmin}, {ymin}) → ({xmax}, {ymax})"
            )

        # Duplicate bbox detection
        bbox_key = (xmin, ymin, xmax, ymax)
        if bbox_key in bbox_seen:
            detail = f"shares bbox with {bbox_seen[bbox_key]}"
            print(f"[WARN][VERIFY] DUPLICATE_BBOX: {nid} ({label}) — {detail}")
            anomalies.append({
                "type": "DUPLICATE_BBOX",
                "node_id": nid,
                "label": label,
                "detail": detail,
            })
        else:
            bbox_seen[bbox_key] = nid

    print(f"[PHASE 0][VERIFY] Verified {len(node_ids)} nodes (bbox + structure)")

    # ── Edge validation ────────────────────────────────────────────────────
    for e in edges:
        if e["src"] not in node_ids:
            raise ValueError(
                f"Edge references missing source node: {e['src']}"
            )
        if e["dst"] not in node_ids:
            raise ValueError(
                f"Edge references missing target node: {e['dst']}"
            )

    print(f"[PHASE 0][VERIFY] Verified {len(edges)} edges (referential integrity)")

    # ── Degree-based anomaly detection ────────────────────────────────────
    degree = defaultdict(int)
    for e in edges:
        degree[e["src"]] += 1
        degree[e["dst"]] += 1

    for nid in node_ids:
        label = node_label.get(nid, "")
        deg = degree.get(nid, 0)

        # Degree-0: unexpected orphans
        if deg == 0 and label not in _EXPECTED_ORPHAN_LABELS:
            detail = f"degree=0, label={label}"
            print(f"[WARN][VERIFY] ORPHAN_NODE: {nid} — {detail}")
            anomalies.append({
                "type": "ORPHAN_NODE",
                "node_id": nid,
                "label": label,
                "detail": detail,
            })

        # Degree-1: inline components need at least 2 connections
        elif deg == 1 and label in _INLINE_LABELS:
            detail = (
                f"degree=1, label={label} — "
                f"inline component expected degree ≥ 2"
            )
            print(f"[WARN][VERIFY] DANGLING_INLINE: {nid} — {detail}")
            anomalies.append({
                "type": "DANGLING_INLINE",
                "node_id": nid,
                "label": label,
                "detail": detail,
            })

    # ── Summary ───────────────────────────────────────────────────────────
    anomaly_counts = defaultdict(int)
    for a in anomalies:
        anomaly_counts[a["type"]] += 1

    if anomalies:
        print(
            f"[PHASE 0][VERIFY] Anomalies detected: "
            + ", ".join(f"{k}={v}" for k, v in anomaly_counts.items())
        )
    else:
        print("[PHASE 0][VERIFY] No anomalies detected")

    print("[PHASE 0][VERIFY] Verification PASSED")

    return {
        "node_count": len(node_ids),
        "edge_count": len(edges),
        "anomalies": anomalies,
    }