# scripts/run_phase3.py
#
# Phase 3 orchestrator — Evidence annotation + structural pattern detection
#
# EXECUTION ORDER:
#   Step 1   — Lift FLOW_EVIDENCE → Evidence nodes + Annotations (arrow-based)
#   Step 1.5 — Boundary flow evidence R7 (inlet/outlet pennant direction)
#   Step 2   — Equipment-based flow evidence R4 (pumps, compressors)
#   Step 3   — Explicit check valve flow evidence R6 (check_valve/nrv labels)
#   Step 3b  — Inferred check valve flow evidence R6b ← NEW-B
#              Queries Neo4j for 'inferred_check_valve' nodes (relabeled by
#              Phase 1 classify_equipment from 'general' degree-2 nodes).
#              Cannot be handled in Step 3 because annotate_check_valve_flow
#              works on the raw GraphML nodes list where labels are still 'general'.
#   Step 5   — Evidence gap detection
#   Step 6   — Dead-end topology inference R5
#   Step 4   — Direction-frequency summary (AFTER steps 3b+6 so topology-
#              inferred LPS are included — GAP-13 fix)
#   Step 7   — seed_confidence
#   Step 8   — Structural pattern detection
#   Step 8.5 — Engineering rule validation Phase 3.5
#   Step 9   — Structural frequency aggregation
#   Step 10  — Structural rarity scoring
#
# GAP-6 FIX: clear_phase3_data removes stale Phase 4 flow properties from
#   equipment Node instances when re-running from PHASE4_COMPLETE.
#
# GAP-13 FIX: _collect_non_arrow_evidence includes 'phase3_topology_inference'
#   and runs AFTER dead-end inference (Step 6). _write_direction_freq_summary
#   runs AFTER that, so topology-inferred LPS have the correct observation count.

import argparse
import os
import sys
import yaml
from collections import defaultdict, Counter
from typing import Dict, Any, Tuple, Set, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.phase3_annotation import pattern_detection, frequency_aggregation, rarity_scoring
from engine.phase3_annotation.boundary_flow import annotate_boundary_flow
from engine.phase3_annotation.equipment_flow import (
    annotate_equipment_flow,
    annotate_check_valve_flow,
    annotate_inferred_check_valve_flow,   # NEW-B
)
from engine.phase3_annotation.engineering_rules import validate_equipment_topology_rules


def load_configs():
    # Only loads storage config — Neo4jLoader() handles its own credential
    # resolution (config/neo4j.yaml → env var overrides: NEO4J_URI/USER/PASSWORD).
    with open(os.path.join(PROJECT_ROOT, "config", "storage.yaml")) as f:
        storage_cfg = yaml.safe_load(f)["storage"]
    return storage_cfg


def _resolve_image_path(loader, pid_id: str) -> str | None:
    """Return the absolute filepath of the PID image, or None if not found."""
    with open(os.path.join(PROJECT_ROOT, "config", "storage.yaml")) as f:
        store_root = yaml.safe_load(f)["storage"]["store_root"]
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.image_path AS image_rel",
            pid_id=pid_id,
        ).single()
    if row is None or not row["image_rel"]:
        return None
    return os.path.join(store_root, row["image_rel"].replace("/", os.sep))


def check_pid_status(loader, pid_id: str) -> str | None:
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.status AS status",
            pid_id=pid_id,
        ).single()
    return row["status"] if row else None


def clear_phase3_data(loader, pid_id: str) -> None:
    """
    Remove all Phase 3 data for this PID.
    Phase 0, 1, 2 data preserved.

    GAP-6 FIX: Also clears stale Phase 4 flow properties from equipment nodes
    so Phase 7 HITL doesn't see violation summaries pointing at deleted Annotations.
    """
    with loader.driver.session(database=loader.database) as s:
        s.run("MATCH (e:Evidence {pid_id: $pid_id}) DETACH DELETE e", pid_id=pid_id)
        s.run("MATCH (a:Annotation {pid_id: $pid_id}) DETACH DELETE a", pid_id=pid_id)
        s.run(
            "MATCH (lps:LogicalPipeSegment {pid_id: $pid_id}) REMOVE lps.seed_confidence",
            pid_id=pid_id,
        )
        # GAP-6: cascade-clear stale Phase 4 violation summary properties
        s.run("""
            MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
            WHERE n.has_rule_violations IS NOT NULL
               OR n.rule_violation_count IS NOT NULL
               OR n.rule_violation_types IS NOT NULL
            REMOVE n.has_rule_violations, n.rule_violation_count, n.rule_violation_types
        """, pid_id=pid_id)
        # GAP-6: cascade-clear stale Phase 4 flow properties on equipment nodes
        s.run("""
            MATCH (n:Node {flow_source: 'phase4_equipment_assignment'})
                  -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
            REMOVE n.flow_state, n.flow_direction, n.flow_confidence,
                   n.flow_source, n.flow_pid_id
        """, pid_id=pid_id)
        s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE2_COMPLETE'",
            pid_id=pid_id,
        )
    print(
        f"[PHASE 3] Cleared Phase 3 data for PID={pid_id} "
        f"(includes Phase 3.5 violations and stale Phase 4 flow summaries)"
    )


def resolve_pid(loader, pid_id: str) -> dict:
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            """
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)-[:HAS_PID]->(pid:PID {pid_id: $pid_id})
            RETURN plant.plant_id AS plant_id, skid.skid_id AS skid_id, pid.status AS status
            """,
            pid_id=pid_id,
        ).single()
    if row is None:
        raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")
    print(f"[PHASE3] PID resolved: {row['plant_id']} / {row['skid_id']} / {pid_id}")
    return dict(row)


def load_nodes_edges(loader, pid_id: str):
    import yaml as _yaml
    from engine.phase0_ingestion.parse_graphml   import parse_graphml
    from engine.phase0_ingestion.normalize_nodes  import normalize_nodes

    with open(os.path.join(PROJECT_ROOT, "config", "storage.yaml")) as f:
        store_root = _yaml.safe_load(f)["storage"]["store_root"]

    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.graphml_path AS graphml_rel",
            pid_id=pid_id,
        ).single()
    if row is None:
        raise ValueError(f"PID '{pid_id}' graphml_path not found.")

    graphml_abs = os.path.join(store_root, row["graphml_rel"].replace("/", os.sep))
    nodes, edges = parse_graphml(graphml_abs)
    nodes = normalize_nodes(nodes)
    return nodes, edges


# ── Step 1 ────────────────────────────────────────────────────────────────────

def _lift_flow_evidence(
    session, pid_id: str,
) -> Tuple[Set[str], Dict[str, Counter]]:
    annotated_lps:    Set[str]           = set()
    direction_counts: Dict[str, Counter] = defaultdict(Counter)

    rows = session.run(
        """
        MATCH (a:Arrow {pid_id: $pid_id})-[r:FLOW_EVIDENCE]->(lps:LogicalPipeSegment)
        RETURN
            a.id               AS arrow_id,
            lps.id             AS lps_id,
            r.direction_hint   AS direction_hint,
            r.cosine_alignment AS cosine_alignment,
            r.confidence       AS confidence,
            r.dx               AS dx,
            r.dy               AS dy,
            r.low_confidence   AS low_confidence,
            r.pixel_direction  AS pixel_direction,
            r.direction_method AS direction_method
        """,
        pid_id=pid_id,
    ).data()

    for r in rows:
        arrow_id       = r.get("arrow_id")
        lps_id         = r.get("lps_id")
        direction_hint = r.get("direction_hint") or "UNKNOWN"
        if not arrow_id or not lps_id:
            continue

        ev_id  = f"ev_{arrow_id}__{lps_id}"
        ann_id = f"ann_obs_{pid_id}_{arrow_id}__{lps_id}"

        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id})
            MERGE (e:Evidence {id: $ev_id})
            ON CREATE SET
              e.pid_id             = $pid_id,
              e.source             = 'phase2_flow_evidence',
              e.arrow_id           = $arrow_id,
              e.observed_direction = $direction,
              e.direction_hint     = $direction,
              e.confidence         = coalesce($confidence, 0.0),
              e.cosine_alignment   = coalesce($cosine, 0.0),
              e.dx                 = coalesce($dx, 0.0),
              e.dy                 = coalesce($dy, 0.0),
              e.low_confidence     = coalesce($low_confidence, false),
              e.pixel_direction    = $pixel_direction,
              e.direction_method   = $direction_method,
              e.first_seen         = datetime()
            ON MATCH SET
              e.confidence         = coalesce($confidence, e.confidence),
              e.cosine_alignment   = coalesce($cosine, e.cosine_alignment),
              e.last_seen          = datetime()
            MERGE (e)-[:ABOUT]->(lps)
            """,
            ev_id=ev_id, pid_id=pid_id, arrow_id=arrow_id, lps_id=lps_id,
            direction=direction_hint,
            confidence=r.get("confidence"), cosine=r.get("cosine_alignment"),
            dx=r.get("dx"), dy=r.get("dy"), low_confidence=r.get("low_confidence"),
            pixel_direction=r.get("pixel_direction"), direction_method=r.get("direction_method"),
        )
        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id}), (e:Evidence {id: $ev_id})
            MERGE (a:Annotation {id: $ann_id})
            ON CREATE SET
              a.pid_id     = $pid_id,
              a.type       = 'direction_observation',
              a.intent     = 'observation',
              a.source     = 'phase3',
              a.first_seen = datetime()
            ON MATCH SET a.last_seen = datetime()
            MERGE (a)-[:ANNOTATES]->(lps)
            MERGE (a)-[:SUPPORTED_BY]->(e)
            """,
            lps_id=lps_id, ev_id=ev_id, ann_id=ann_id, pid_id=pid_id,
        )
        direction_counts[lps_id][direction_hint] += 1
        annotated_lps.add(lps_id)

    return annotated_lps, direction_counts


# ── Step 1b: Collect non-arrow Evidence ──────────────────────────────────────
#
# GAP-13 FIX: 'phase3_topology_inference' included.
# This function is called AFTER topology inference (Step 6) so direction_counts
# is complete before _write_direction_freq_summary runs.

def _collect_non_arrow_evidence(
    session,
    pid_id: str,
    direction_counts: Dict[str, Counter],
    annotated_lps: Set[str],
) -> None:
    rows = session.run(
        """
        MATCH (e:Evidence {pid_id: $pid_id})-[:ABOUT]->(lps:LogicalPipeSegment)
        WHERE e.source IN [
            'phase3_boundary_semantics',
            'phase3_equipment_semantics',
            'phase3_check_valve',
            'phase3_topology_inference'
        ]
        RETURN lps.id AS lps_id, e.observed_direction AS direction
        """,
        pid_id=pid_id,
    ).data()
    for r in rows:
        lps_id    = r.get("lps_id")
        direction = r.get("direction") or "UNKNOWN"
        if lps_id:
            direction_counts[lps_id][direction] += 1
            annotated_lps.add(lps_id)


# ── Step 4: Direction-frequency summary ───────────────────────────────────────

def _write_direction_freq_summary(
    session, pid_id: str, direction_counts: Dict[str, Counter]
) -> None:
    for lps_id, counter in direction_counts.items():
        total  = sum(counter.values())
        ann_id = f"ann_freq_summary_{pid_id}_{lps_id}"
        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id})
            MERGE (a:Annotation {id: $ann_id})
            ON CREATE SET
              a.pid_id             = $pid_id,
              a.type               = 'direction_frequency_summary',
              a.intent             = 'statistical_summary',
              a.source             = 'phase3_freq_summary',
              a.total_observations = $total,
              a.first_seen         = datetime()
            ON MATCH SET
              a.total_observations = $total,
              a.last_seen          = datetime()
            MERGE (a)-[:ANNOTATES]->(lps)
            """,
            lps_id=lps_id, ann_id=ann_id, pid_id=pid_id, total=int(total),
        )
        for direction, count in counter.items():
            ev_id      = f"ev_freq_{pid_id}_{lps_id}_{direction}"
            normalized = float(count / total) if total else 0.0
            session.run(
                """
                MATCH (a:Annotation {id: $ann_id})
                MATCH (lps:LogicalPipeSegment {id: $lps_id})
                MERGE (e:Evidence {id: $ev_id})
                ON CREATE SET
                  e.pid_id             = $pid_id,
                  e.type               = 'direction_frequency',
                  e.direction          = $direction,
                  e.observed_direction = $direction,
                  e.count              = $count,
                  e.normalized         = $normalized,
                  e.source             = 'phase3_freq_summary',
                  e.confidence         = 1.0,
                  e.first_seen         = datetime()
                ON MATCH SET
                  e.count              = $count,
                  e.normalized         = $normalized,
                  e.observed_direction = $direction,
                  e.last_seen          = datetime()
                MERGE (a)-[:SUPPORTED_BY]->(e)
                MERGE (e)-[:ABOUT]->(lps)
                """,
                ann_id=ann_id, ev_id=ev_id, lps_id=lps_id,
                pid_id=pid_id, direction=direction,
                count=int(count), normalized=normalized,
            )


# ── Step 5: Evidence gap detection ───────────────────────────────────────────

def _detect_evidence_gaps(session, pid_id: str) -> int:
    # Stamp phase4_hint directly on the LPS node instead of creating heavyweight
    # Annotation nodes. Phase 4 pre-flight detects gap LPS via a direct Evidence
    # absence check and stamps the same hint value without needing these nodes.
    # Phase 3 Step 6 (dead-end inference) uses this property to select candidates.
    result = session.run(
        """
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
        WHERE NOT (lps)<-[:ABOUT]-(:Evidence {pid_id: $pid_id})
        SET lps.phase4_hint = 'direction_evidence_missing'
        RETURN count(lps) AS c
        """,
        pid_id=pid_id,
    )
    return result.single()["c"]


# ── Step 6: Dead-end topology inference ──────────────────────────────────────

def _infer_dead_end_directions(session, pid_id: str) -> int:
    _DEAD_END_CONFIDENCE = 0.60
    inferred = 0

    rows = session.run(
        """
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
        WHERE lps.phase4_hint = 'direction_evidence_missing'
        WITH lps,
             [(lps)-[:ADJACENT_VIA_NODES]-(nb:LogicalPipeSegment) | nb] AS neighbours
        WHERE size(neighbours) = 1
        WITH lps, neighbours[0] AS nb_lps
        MATCH (nb_lps)<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WHERE e.observed_direction IN ['FORWARD', 'REVERSE']
          AND e.confidence >= 0.5
        WITH lps, nb_lps,
             e.observed_direction AS nb_dir,
             avg(e.confidence)    AS nb_conf
        RETURN lps.id   AS lps_id,
               nb_lps.id AS nb_lps_id,
               nb_dir, nb_conf
        LIMIT 500
        """,
        pid_id=pid_id,
    ).data()

    for r in rows:
        lps_id    = r["lps_id"]
        nb_lps_id = r["nb_lps_id"]
        confidence = round(min(_DEAD_END_CONFIDENCE, float(r["nb_conf"]) * 0.75), 3)

        ev_id  = f"ev_topology_{pid_id}_{lps_id}"
        ann_id = f"ann_topology_{pid_id}_{lps_id}"

        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id})
            MERGE (e:Evidence {id: $ev_id})
            ON CREATE SET
              e.pid_id             = $pid_id,
              e.source             = 'phase3_topology_inference',
              e.inferred_from      = $nb_lps_id,
              e.observed_direction = 'FORWARD',
              e.direction_hint     = 'FORWARD',
              e.confidence         = $confidence,
              e.low_confidence     = ($confidence < 0.5),
              e.first_seen         = datetime()
            ON MATCH SET e.last_seen = datetime()
            MERGE (e)-[:ABOUT]->(lps)
            """,
            ev_id=ev_id, pid_id=pid_id, lps_id=lps_id,
            nb_lps_id=nb_lps_id, confidence=confidence,
        )
        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id}), (e:Evidence {id: $ev_id})
            MERGE (a:Annotation {id: $ann_id})
            ON CREATE SET
              a.pid_id        = $pid_id,
              a.type          = 'direction_observation',
              a.intent        = 'topology_inference',
              a.source        = 'phase3_topology_inference',
              a.inferred_from = $nb_lps_id,
              a.first_seen    = datetime()
            ON MATCH SET a.last_seen = datetime()
            MERGE (a)-[:ANNOTATES]->(lps)
            MERGE (a)-[:SUPPORTED_BY]->(e)
            """,
            ann_id=ann_id, ev_id=ev_id, pid_id=pid_id,
            lps_id=lps_id, nb_lps_id=nb_lps_id,
        )
        session.run(
            """
            MATCH (lps:LogicalPipeSegment {id: $lps_id})
            REMOVE lps.phase4_hint
            """,
            lps_id=lps_id,
        )
        inferred += 1

    return inferred


# ── Step 7: seed_confidence ───────────────────────────────────────────────────

def _write_seed_confidence(session, pid_id: str) -> int:
    result = session.run(
        """
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
        OPTIONAL MATCH (lps)<-[:ABOUT]-(e:Evidence {pid_id: $pid_id})
        WITH lps,
             count(e) AS n_total,
             size([x IN collect(e) WHERE x.observed_direction = 'FORWARD']) AS n_fwd,
             avg(CASE WHEN e.confidence IS NOT NULL THEN toFloat(e.confidence) END) AS avg_conf
        WITH lps, n_total, n_fwd, avg_conf,
             CASE WHEN n_total > 0 THEN toFloat(n_fwd)/toFloat(n_total) ELSE 0.0 END AS fwd_fraction
        SET lps.seed_confidence = round(
              fwd_fraction * coalesce(avg_conf, 0.0) * 1000
            ) / 1000.0
        RETURN count(lps) AS updated
        """,
        pid_id=pid_id,
    )
    rec = result.single()
    updated = rec["updated"] if rec else 0
    print(f"[PHASE3][SEED] seed_confidence written to {updated} LPS nodes | PID={pid_id}")
    return updated


def _query_violation_count(session, pid_id: str) -> int:
    rec = session.run(
        "MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'}) RETURN count(a) AS c",
        pid_id=pid_id,
    ).single()
    return int(rec["c"]) if rec else 0


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_phase3(pid_id: str, loader, nodes: List[Dict], edges: List[Dict]) -> None:
    print(f"\n========== PHASE 3 START | PID={pid_id} ==========\n")

    # Resolve image path once — used by Step 1.5 boundary flow evidence.
    image_path = _resolve_image_path(loader, pid_id)
    if image_path is None:
        print(f"[PHASE3][WARN] PID image path not found; boundary flow evidence (R7) will use geometric fallback.")

    with loader.driver.session(database=loader.database) as session:

        ps_count  = session.run("MATCH (ps:PipeSegment {pid_id:$p}) RETURN count(ps) AS c", p=pid_id).single()["c"]
        lps_count = session.run("MATCH (lps:LogicalPipeSegment {pid_id:$p}) RETURN count(lps) AS c", p=pid_id).single()["c"]
        fe_count  = session.run("MATCH (a:Arrow {pid_id:$p})-[r:FLOW_EVIDENCE]->() RETURN count(r) AS c", p=pid_id).single()["c"]

        print(f"[PHASE3] Graph: PS={ps_count}, LPS={lps_count}, FLOW_EVIDENCE={fe_count}")
        if fe_count == 0:
            raise RuntimeError(f"No FLOW_EVIDENCE for PID={pid_id}. Run run_phase2.py --pid first.")

        # ── Step 1 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 1 — Lifting FLOW_EVIDENCE -> Evidence nodes + Annotations...")
        annotated_lps, direction_counts = _lift_flow_evidence(session, pid_id)
        print(f"[PHASE3] Arrow Evidence lifted: {len(annotated_lps)} LPS annotated")

        # ── Step 1.5 ──────────────────────────────────────────────────────
        # R7 — Boundary pennant direction inference.
        # inlet/outlet pennants carry directional information (tip points toward
        # flow) exactly like arrows.  We use the same pixel-tip + cosine approach
        # (Moon 2021 §3.1) so the result is orientation-agnostic: horizontal,
        # vertical, or any edge placement are all handled identically.
        print("[PHASE3] Step 1.5 — Boundary flow evidence from inlet/outlet nodes (R7)...")
        boundary_count, boundary_dir_counts = annotate_boundary_flow(
            session, pid_id, image_path or ""
        )
        for lps_id, ctr in boundary_dir_counts.items():
            for d, n in ctr.items():
                direction_counts[lps_id][d] += n
            annotated_lps.add(lps_id)
        print(f"[PHASE3] Boundary Evidence: {boundary_count} inlet/outlet LPS annotated")

        # ── Step 2 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 2 — Equipment-based flow evidence (R4)...")
        annotate_equipment_flow(session, pid_id, nodes)

        # ── Step 3 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 3 — Explicit check valve flow evidence (R6)...")
        annotate_check_valve_flow(session, pid_id, nodes, edges)

        # ── Step 3b NEW-B ─────────────────────────────────────────────────
        # Handles 'inferred_check_valve' nodes (relabeled from 'general' by
        # Phase 1 classify_equipment.py).  Must query Neo4j — not in raw nodes list.
        print("[PHASE3] Step 3b — Inferred check valve flow evidence (R6b)...")
        annotate_inferred_check_valve_flow(session, pid_id)

        # ── Step 5 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 5 — Detecting evidence gaps...")
        gap_count = _detect_evidence_gaps(session, pid_id)
        print(f"[PHASE3] LPS still missing Evidence after all sources: {gap_count}")

        # ── Step 6 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 6 — Dead-end topology inference (R5)...")
        inferred_count = _infer_dead_end_directions(session, pid_id)
        print(f"[PHASE3] Dead-end LPS with inferred direction: {inferred_count}")

        # ── GAP-13: Collect ALL non-arrow evidence AFTER topology inference ─
        # Includes 'phase3_topology_inference' so direction_freq_summary
        # accurately reflects ALL evidence sources.
        _collect_non_arrow_evidence(session, pid_id, direction_counts, annotated_lps)

        # ── Step 4 (runs after step 6 — GAP-13 fix) ──────────────────────
        print("[PHASE3] Step 4 — Writing direction-frequency summaries...")
        _write_direction_freq_summary(session, pid_id, direction_counts)

        # ── Step 7 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 7 — Writing seed_confidence to LPS nodes (R3)...")
        _write_seed_confidence(session, pid_id)

        # ── Step 8 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 8 — Running structural pattern detection...")
        pattern_detection.detect_structural_patterns(session, pid_id)

        # ── Step 8.5 ──────────────────────────────────────────────────────
        print("[PHASE3] Step 8.5 — Engineering rule validation (Phase 3.5)...")
        validate_equipment_topology_rules(session, pid_id)
        violation_count = _query_violation_count(session, pid_id)

        # ── Step 9 ────────────────────────────────────────────────────────
        print("[PHASE3] Step 9 — Running structural frequency aggregation...")
        frequency_aggregation.compute_structural_frequencies(session, pid_id)

        # ── Step 10 ───────────────────────────────────────────────────────
        print("[PHASE3] Step 10 — Running structural rarity scoring (R1)...")
        rarity_scoring.compute_structural_rarity(session, pid_id)

        final_gap = session.run(
            "MATCH (lps:LogicalPipeSegment {pid_id:$p}) WHERE NOT (lps)<-[:ABOUT]-(:Evidence {pid_id:$p}) RETURN count(lps) AS c",
            p=pid_id,
        ).single()["c"]
        ann_pid = session.run("MATCH (a:Annotation {pid_id:$p}) RETURN count(a) AS c", p=pid_id).single()["c"]
        ev_pid  = session.run("MATCH (e:Evidence {pid_id:$p}) RETURN count(e) AS c", p=pid_id).single()["c"]

        print(f"\n========== PHASE 3 SUMMARY | PID={pid_id} ==========")
        print(f"  Evidence nodes (this PID)          : {ev_pid}")
        print(f"  Annotations   (this PID)           : {ann_pid}")
        print(f"  LPS with Evidence (all sources)    : {len(annotated_lps)}")
        print(f"  Boundary LPS annotated (R7)        : {boundary_count}")
        print(f"  LPS gaps after all sources         : {gap_count}")
        print(f"  Dead-end LPS with inferred dir     : {inferred_count}")
        print(f"  LPS still missing Evidence (final) : {final_gap}")
        print(f"  Engineering rule violations        : {violation_count}  ← Phase 3.5")
        print(f"========== PHASE 3 COMPLETE | PID={pid_id} ==========\n")

    with loader.driver.session(database=loader.database) as session:
        session.run(
            "MATCH (pid:PID {pid_id:$p}) SET pid.status = 'PHASE3_COMPLETE'", p=pid_id
        )


def main():
    parser = argparse.ArgumentParser(description="Run Phase 3 annotation engine.")
    parser.add_argument("--pid",   required=True,       help="PID ID as registered in Neo4j")
    parser.add_argument("--force", action="store_true", help="Skip re-ingestion prompt")
    args = parser.parse_args()

    # Neo4jLoader() resolves credentials itself: config/neo4j.yaml then env vars
    # (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) — no YAML read needed here.
    loader = Neo4jLoader()

    try:
        resolve_pid(loader, args.pid)

        already_ingested_statuses = {"PHASE3_COMPLETE", "PHASE4_COMPLETE", "PHASE5_COMPLETE", "PHASE6_COMPLETE", "PHASE7_COMPLETE"}
        current_status = check_pid_status(loader, args.pid)

        if current_status is None:
            raise ValueError(f"PID '{args.pid}' not found. Run register_pid.py first.")
        if current_status not in {"PHASE2_COMPLETE"} | already_ingested_statuses:
            raise RuntimeError(
                f"PID '{args.pid}' has status='{current_status}'. "
                f"Phase 3 requires PHASE2_COMPLETE. Run Phases 0→1→2 first."
            )

        if current_status in already_ingested_statuses:
            print(
                f"\n[PHASE 3] WARNING: PID={args.pid} already has status='{current_status}'.\n"
                f"  Re-running clears Evidence, Annotations (including Phase 3.5 violations)\n"
                f"  and stale Phase 4 flow properties on equipment nodes.\n"
                f"  Phase 0, 1, and 2 data is preserved.\n"
            )
            if args.force:
                print("[PHASE 3] --force flag set. Clearing and re-running.")
                proceed = True
            else:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                proceed = answer == "y"
            if not proceed:
                print("[PHASE 3] Aborted. No changes made.")
                loader.close()
                return
            clear_phase3_data(loader, args.pid)

        print("[PHASE3] Loading nodes and edges from GraphML...")
        nodes, edges = load_nodes_edges(loader, args.pid)
        print(f"[PHASE3] Loaded {len(nodes)} nodes, {len(edges)} edges")

        run_phase3(args.pid, loader, nodes, edges)

    finally:
        loader.close()
        print("[INFO] Neo4j connection closed.")


if __name__ == "__main__":
    main()