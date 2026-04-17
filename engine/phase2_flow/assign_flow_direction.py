# engine/phase2_flow/assign_flow_direction.py
#
# Phase 2 — Evidence-only flow inference.
#
# GAP-14 FIX (seg_vec_source not persisted):
#   Step 6 adds item["seg_vec_source"] = "connector_span" or "arrow_vec_fallback"
#   to evidence items when the primary seg_nodes < 2 path fires. Previously this
#   property was only written to the local dict and the logs/phase2_evidence.json
#   cache — it was never included in the FLOW_EVIDENCE relationship SET clause in
#   Step 10. The stated observability purpose was only half-fulfilled.
#   Fixed: seg_vec_source is now included in ON CREATE SET for FLOW_EVIDENCE rels.

import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from .arrow_binding        import bind_arrows_to_segments
from .arrow_debug          import print_all_arrow_bindings
from .arrow_geometry       import detect_arrow_geometry
from .arrow_pixel_analysis import arrow_cos_alignment, detect_arrow_tip_direction

_LOGS_DIR      = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
)
_EVIDENCE_PATH = os.path.join(_LOGS_DIR, "phase2_evidence.json")


def safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def safe_bbox_center(attrs: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    if not isinstance(attrs, dict):
        return None
    xmin = attrs.get("xmin")
    xmax = attrs.get("xmax")
    ymin = attrs.get("ymin")
    ymax = attrs.get("ymax")
    if any(v is None for v in (xmin, xmax, ymin, ymax)):
        return None
    return (
        (safe_float(xmin) + safe_float(xmax)) / 2.0,
        (safe_float(ymin) + safe_float(ymax)) / 2.0,
    )


def node_center(attrs):
    return safe_bbox_center(attrs)


def safe_vector(p1, p2):
    if not p1 or not p2:
        return (0.0, 0.0)
    return (p2[0] - p1[0], p2[1] - p1[1])


def neighbor_axis(arrow_id, edges, node_index, centers):
    """
    Determine pipe axis (H or V) from direct GraphML neighbors of an arrow node.
    """
    arrow_node   = node_index.get(arrow_id)
    arrow_attrs  = (arrow_node.get("attrs") if isinstance(arrow_node, dict) else None) or {}
    arrow_center = safe_bbox_center(arrow_attrs)
    if not arrow_center:
        return None, 0.0, 0.0

    ax, ay = arrow_center
    total_h = 0.0
    total_v = 0.0

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get("src"), edge.get("dst")
        nb_id = dst if src == arrow_id and isinstance(dst, str) else \
                src  if dst == arrow_id and isinstance(src, str) else None
        if not nb_id:
            continue

        nb_center = centers.get(nb_id)
        if not nb_center:
            nb_node  = node_index.get(nb_id)
            nb_attrs = (nb_node.get("attrs") if isinstance(nb_node, dict) else None) or {}
            nb_center = safe_bbox_center(nb_attrs)
        if not nb_center:
            continue

        total_h += abs(nb_center[0] - ax)
        total_v += abs(nb_center[1] - ay)

    if total_h == 0.0 and total_v == 0.0:
        return None, 0.0, 0.0

    return ("H" if total_h > total_v else "V"), total_h, total_v


def assign_flow_direction(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    loader,
    pid_id: str,
    symbol_dict: Optional[Dict[str, Any]] = None,
    image_path: Optional[str] = None,
    visual_debug: bool = False,
    write_to_db: bool = True,
) -> None:
    """
    Phase 2: Generate FLOW_EVIDENCE based on arrows.
    Evidence-only — writes FLOW_EVIDENCE relationships to Neo4j.
    """
    if image_path is None:
        raise ValueError("image_path is required")
    if not isinstance(pid_id, str) or not pid_id:
        raise ValueError("pid_id is required and must be a non-empty string")

    print("========== PHASE 2 START ==========")

    # ── 1. LogicalPipeSegment → endpoint nodes ────────────────────────────
    seg_map:      Dict[str, List[str]]     = {}
    node_to_seg:  Dict[str, List[str]]     = defaultdict(list)

    with loader.driver.session(database=loader.database) as session:
        result = session.run(
            """
            MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ENDPOINT_OF]-(n:Node)
            WITH lps, n
            ORDER BY n.id ASC
            RETURN lps.id AS pid, collect(n.id) AS nodes
            """,
            pid_id=pid_id,
        )
        for rec in result:
            pid   = rec.get("pid")
            nlist = rec.get("nodes") or []
            if not isinstance(pid, str):
                continue
            seg_map[pid] = sorted(nid for nid in nlist if isinstance(nid, str))
            for nid in seg_map[pid]:
                node_to_seg[nid].append(pid)

    print(f"[INFO] LPS loaded for pid_id={pid_id}: {len(seg_map)} segments")

    # ── 2. Node centers ───────────────────────────────────────────────────
    centers:    Dict[str, Tuple[float, float]] = {}
    node_index: Dict[str, Dict[str, Any]]      = {}

    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid   = n.get("id")
        attrs = n.get("attrs")
        if not isinstance(nid, str):
            continue
        node_index[nid] = n
        c = node_center(attrs)
        if c is not None:
            centers[nid] = c

    # ── 3. Geometry-based arrow detection (debug) ─────────────────────────
    try:
        arrow_geo = detect_arrow_geometry(nodes)
        print(f"[DEBUG] Detected {len(arrow_geo)} arrows via geometry")
    except Exception as e:
        print(f"[WARN] detect_arrow_geometry failed: {e}")
        arrow_geo = []

    # ── 4. Bind arrows to LogicalPipeSegments ─────────────────────────────
    try:
        evidence = bind_arrows_to_segments(nodes, edges, seg_map, symbol_dict=symbol_dict)
    except Exception as e:
        print(f"[ERROR] bind_arrows_to_segments failed: {e}")
        evidence = []

    if not isinstance(evidence, list):
        evidence = []

    # ── 6. Bbox geometry alignment ────────────────────────────────────────
    _SQUARE_LO    = 0.95
    _SQUARE_HI    = 1.05
    _CONF_DIVISOR = 0.5
    _fallback_count = 0

    # Load image once in grayscale for pixel-level tip detection.
    # image_path is required by the function signature so this is always set.
    _pid_image = None
    try:
        _pid_image = Image.open(image_path).convert("L")
        print(f"[INFO] Step 6: loaded P&ID image for pixel tip analysis ({image_path})")
    except Exception as _img_err:
        print(f"[WARN] Step 6: could not load image for pixel tip analysis: {_img_err}")

    for item in evidence:
        if not isinstance(item, dict):
            continue

        arrow_id = item.get("arrow_id")
        if not isinstance(arrow_id, str):
            item.update({"cosine_alignment": 0.0, "direction_hint": "UNKNOWN",
                          "confidence": 0.0, "low_confidence": True})
            continue

        arrow_node  = node_index.get(arrow_id)
        arrow_attrs = (arrow_node.get("attrs") if isinstance(arrow_node, dict) else None) or {}
        a_xmin = safe_float(arrow_attrs.get("xmin"))
        a_xmax = safe_float(arrow_attrs.get("xmax"))
        a_ymin = safe_float(arrow_attrs.get("ymin"))
        a_ymax = safe_float(arrow_attrs.get("ymax"))
        bbox_w = a_xmax - a_xmin
        bbox_h = a_ymax - a_ymin
        ratio  = (bbox_w / bbox_h) if bbox_h > 0 else 1.0

        confidence     = round(min(1.0, abs(ratio - 1.0) / _CONF_DIVISOR), 3)
        low_confidence = confidence < 0.5

        # ── Pixel tip detection — deterministic signed direction ───────────
        # Count dark pixels in the first vs last third of the dominant axis.
        # The pointed tip narrows → fewer dark pixels at its extreme edge.
        # This produces a SIGNED arrow_vec (e.g. WEST → (-bbox_w, 0)) so the
        # downstream cosine against seg_vec gives FORWARD/REVERSE correctly
        # without any assumption about plant flow-direction convention.
        pixel_direction = None
        if _pid_image is not None:
            try:
                pixel_direction = detect_arrow_tip_direction(
                    _pid_image, a_xmin, a_ymin, a_xmax, a_ymax
                )
            except Exception:
                pixel_direction = None

        if pixel_direction is not None:
            _PDIR_VEC = {
                "EAST":  ( bbox_w,  0.0),
                "WEST":  (-bbox_w,  0.0),
                "SOUTH": ( 0.0,   bbox_h),
                "NORTH": ( 0.0,  -bbox_h),
            }
            arrow_vec      = _PDIR_VEC.get(pixel_direction, (bbox_w, 0.0))
            confidence     = 1.0
            low_confidence = False
            item["pixel_direction"]  = pixel_direction
            item["direction_method"] = "pixel_tip"
        else:
            # Fallback: unsigned bbox-aspect assumption (assumes right or down)
            if ratio > _SQUARE_HI:
                arrow_vec = (bbox_w, 0.0)
            elif ratio < _SQUARE_LO:
                arrow_vec = (0.0, bbox_h)
            else:
                arrow_vec = (bbox_w, 0.0)
            item["direction_method"] = "bbox_aspect"

            if confidence < 0.5:
                nb_axis, nb_h, nb_v = neighbor_axis(arrow_id, edges, node_index, centers)
                if nb_axis == "H":
                    arrow_vec  = (bbox_w, 0.0)
                    confidence = round(nb_h / (nb_h + nb_v + 1e-9), 3)
                    item["neighbor_resolved"] = True
                elif nb_axis == "V":
                    arrow_vec  = (0.0, bbox_h)
                    confidence = round(nb_v / (nb_h + nb_v + 1e-9), 3)
                    item["neighbor_resolved"] = True
                else:
                    item.update({
                        "dx": 0.0, "dy": 0.0,
                        "cosine_alignment": 0.0,
                        "direction_hint": "UNKNOWN",
                        "confidence": 0.0,
                        "low_confidence": True,
                        "bbox_ambiguous": True,
                    })
                    continue
                low_confidence = confidence < 0.5

        seg_id    = item.get("pipe_segment_id")
        seg_nodes = seg_map.get(seg_id, []) if isinstance(seg_id, str) else []

        if len(seg_nodes) >= 2:
            # ── Spatial ordering per literature (Moon 2021 §3.1, Yu 2019 §5.3) ──
            # "Start point is at the left side for horizontal lines and at the top
            # for vertical lines" — sort by dominant spatial axis so seg_vec always
            # points right (H) or down (V).  Alphabetical node-ID sorting was causing
            # false REVERSE hints whenever the alphabetically-first endpoint happened
            # to sit on the right/bottom side of the physical segment.
            pts_ids = [(centers[n], n) for n in seg_nodes if n in centers]
            if len(pts_ids) >= 2:
                x_span = max(t[0][0] for t in pts_ids) - min(t[0][0] for t in pts_ids)
                y_span = max(t[0][1] for t in pts_ids) - min(t[0][1] for t in pts_ids)
                if x_span >= y_span:  # horizontal segment
                    pts_ids.sort(key=lambda t: (t[0][0], t[1]))  # left → right
                else:                 # vertical segment
                    pts_ids.sort(key=lambda t: (t[0][1], t[1]))  # top  → bottom
                p1, p2 = pts_ids[0][0], pts_ids[-1][0]
                seg_vec = safe_vector(p1, p2)
                item["seg_vec_source"] = "spatial_sort"
            else:
                seg_vec = (0.0, 0.0)
        else:
            sn = item.get("start_node")
            en = item.get("end_node")
            sc = centers.get(sn) if isinstance(sn, str) else None
            ec = centers.get(en) if isinstance(en, str) else None
            if sc and ec:
                seg_vec = safe_vector(sc, ec)
                item["seg_vec_source"] = "connector_span"
            else:
                seg_vec = arrow_vec
                item["seg_vec_source"] = "arrow_vec_fallback"
            _fallback_count += 1

        try:
            alignment = float(arrow_cos_alignment(seg_vec, arrow_vec))
        except Exception:
            alignment = 0.0

        # ── Cross-axis confidence penalty (bbox_aspect fallback only) ─────
        # Pixel-determined directions already carry confidence = 1.0 and the
        # signed arrow_vec is correct, so no penalty is needed.
        # For bbox-aspect fallbacks, penalise when arrow axis ≠ segment axis.
        if pixel_direction is None:
            arrow_is_h = (
                ratio > _SQUARE_HI
                or (ratio >= _SQUARE_LO and abs(arrow_vec[0]) >= abs(arrow_vec[1]))
            )
            seg_is_h = abs(seg_vec[0]) >= abs(seg_vec[1])
            if arrow_is_h != seg_is_h:
                confidence = round(confidence * 0.5, 3)

        # ── Direction threshold raised 0.1 → 0.3 (literature-calibrated) ─────
        # With spatially-ordered seg_vec, axis-aligned H-on-H / V-on-V cosines
        # are ≈ 1.0.  Raising the dead-band to ±0.3 correctly classifies weak
        # near-perpendicular alignments (cosine 0.1–0.3) as UNKNOWN rather than
        # falsely committing to FORWARD or REVERSE.
        direction_hint = (
            "FORWARD"  if alignment >  0.3
            else "REVERSE" if alignment < -0.3
            else "UNKNOWN"
        )

        item["dx"]               = round(float(arrow_vec[0]), 3)
        item["dy"]               = round(float(arrow_vec[1]), 3)
        item["cosine_alignment"] = round(alignment, 3)
        item["direction_hint"]   = direction_hint
        item["confidence"]       = confidence
        item["low_confidence"]   = low_confidence

    if _fallback_count:
        print(f"[DEBUG] Step 6 seg_vec fallback: {_fallback_count} items used connector-span proxy.")

    # ── 5b. Deduplicate per (arrow, LPS) pair ────────────────────────────
    _HINT_RANK = {"FORWARD": 2, "REVERSE": 2, "UNKNOWN": 1}

    best_by_arrow_lps: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        aid = ev.get("arrow_id")
        sid = ev.get("pipe_segment_id")
        if not isinstance(aid, str) or not isinstance(sid, str):
            continue
        key  = (aid, sid)
        prev = best_by_arrow_lps.get(key)
        if not prev:
            best_by_arrow_lps[key] = ev
            continue
        ev_conf   = safe_float(ev.get("confidence", 0))
        prev_conf = safe_float(prev.get("confidence", 0))
        ev_rank   = _HINT_RANK.get(ev.get("direction_hint", "UNKNOWN"), 1)
        prev_rank = _HINT_RANK.get(prev.get("direction_hint", "UNKNOWN"), 1)
        if (ev_conf, ev_rank) > (prev_conf, prev_rank):
            best_by_arrow_lps[key] = ev

    evidence = list(best_by_arrow_lps.values())

    # ── 7. Debug sample ──────────────────────────────────────────────────
    print("[DEBUG] Printing sample of 8 arrow bindings (1 per arrow)")
    try:
        _seen_aids: set = set()
        _sample: list   = []
        for _ev in evidence:
            _aid = _ev.get("arrow_id") if isinstance(_ev, dict) else None
            if _aid and _aid not in _seen_aids:
                _seen_aids.add(_aid)
                _sample.append(_ev)
            if len(_sample) >= 8:
                break
        print_all_arrow_bindings(_sample)
    except Exception:
        print("[WARN] print_all_arrow_bindings failed")

    # ── 8. Visual debug overlay ──────────────────────────────────────────
    if visual_debug:
        try:
            img  = Image.open(image_path).convert("RGBA")
            draw = ImageDraw.Draw(img)
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                aid   = item.get("arrow_id")
                anode = node_index.get(aid) if isinstance(aid, str) else None
                if not isinstance(anode, dict):
                    continue
                center = safe_bbox_center(anode.get("attrs"))
                if not center:
                    continue
                x, y  = center
                ax    = x + safe_float(item.get("dx"))
                ay    = y + safe_float(item.get("dy"))
                color = (0, 200, 0, 200) if item.get("direction_hint") == "FORWARD" else (200, 0, 0, 200)
                draw.line([(x, y), (ax, ay)], fill=color, width=3)
            out = os.path.splitext(image_path)[0] + "_phase2_debug.png"
            img.save(out)
            print(f"[INFO] Visual debug overlay saved: {out}")
        except Exception as e:
            print(f"[ERROR] Visual overlay failed: {e}")

    # ── 9. Cache evidence to logs/ ───────────────────────────────────────
    try:
        os.makedirs(_LOGS_DIR, exist_ok=True)
        with open(_EVIDENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2)
        print(f"[INFO] Evidence cached: {_EVIDENCE_PATH}")
    except Exception as e:
        print(f"[WARN] Failed to write evidence cache: {e}")

    # ── 10. Persist FLOW_EVIDENCE relationships ──────────────────────────
    # GAP-14 FIX: seg_vec_source is now included in ON CREATE SET so the
    # observability property is actually persisted to Neo4j and not just
    # stored in the local dict and JSON cache.
    if write_to_db:
        written = 0
        with loader.driver.session(database=loader.database) as session:
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                aid = item.get("arrow_id")
                pid = item.get("pipe_segment_id")
                if not isinstance(aid, str) or not isinstance(pid, str):
                    continue
                try:
                    session.run(
                        """
                        MERGE (a:Arrow {id: $aid, pid_id: $pid_id})
                        ON CREATE SET a.pid_id = $pid_id
                        MERGE (lps:LogicalPipeSegment {id: $pid, pid_id: $pid_id})
                        MERGE (a)-[r:FLOW_EVIDENCE {source: 'phase2'}]->(lps)
                        ON CREATE SET
                            r.direction_hint   = $dir,
                            r.cosine_alignment = $cos,
                            r.confidence       = $conf,
                            r.dx               = $dx,
                            r.dy               = $dy,
                            r.low_confidence   = $low,
                            r.seg_vec_source   = $seg_vec_source,
                            r.pixel_direction  = $pixel_direction,
                            r.direction_method = $direction_method,
                            r.created_at       = datetime()
                        ON MATCH SET
                            r.last_seen        = datetime()
                        """,
                        {
                            "aid":             aid,
                            "pid":             pid,
                            "pid_id":          pid_id,
                            "dir":             item.get("direction_hint"),
                            "cos":             item.get("cosine_alignment"),
                            "conf":            item.get("confidence"),
                            "dx":              item.get("dx"),
                            "dy":              item.get("dy"),
                            "low":             item.get("low_confidence"),
                            "seg_vec_source":  item.get("seg_vec_source"),
                            "pixel_direction": item.get("pixel_direction"),
                            "direction_method":item.get("direction_method"),
                        },
                    )
                    written += 1
                except Exception as e:
                    print(f"[WARN] Failed to persist FLOW_EVIDENCE {aid}→{pid}: {e}")
        print(f"[NEO4J] FLOW_EVIDENCE relationships written: {written}")

    # ── 11. Summary ──────────────────────────────────────────────────────
    fwd = sum(1 for e in evidence if isinstance(e, dict) and e.get("direction_hint") == "FORWARD")
    rev = sum(1 for e in evidence if isinstance(e, dict) and e.get("direction_hint") == "REVERSE")
    unk = sum(1 for e in evidence if isinstance(e, dict) and e.get("direction_hint") == "UNKNOWN")
    low = sum(1 for e in evidence if isinstance(e, dict) and e.get("low_confidence"))
    unique_arrows = len({e.get("arrow_id") for e in evidence if isinstance(e, dict)})
    unique_lps    = len({e.get("pipe_segment_id") for e in evidence if isinstance(e, dict)})
    print(
        f"[SUMMARY] FORWARD={fwd} | REVERSE={rev} | UNKNOWN={unk} | LOW_CONF={low}"
        f" | TOTAL={len(evidence)} (arrows={unique_arrows}, lps={unique_lps})"
    )
    print("========== PHASE 2 COMPLETE ==========")