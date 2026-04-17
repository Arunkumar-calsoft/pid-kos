# scripts/run_phase1.py
#
# Phase 1 entry point — Deterministic Structural Reconstruction.
#
# Usage:
#   python scripts/run_phase1.py --pid PID_2
#   python scripts/run_phase1.py --pid PID_2 --force
#
# Responsibilities:
#   1.0  Parse + normalize        (reuses Phase 0 engine modules)
#   1.1  Group edges → PipeSegments
#   1.2  Persist PipeSegments to Neo4j
#   1.3  Structural classification (CONNECTOR / SYMBOL / BOUNDARY)
#   1.3b Equipment label inference   ← NEW-B: infer 'general' → 'inferred_check_valve'
#   1.3c Tank functional role        ← NEW-A: stamp functional_label='pump' on small tanks
#   1.4  Pre-collapse validation
#   1.5  Logical collapse → LogicalPipeSegments + LPS adjacency
#   1.6  Verify LPS adjacency
#   1.7  PS endpoint propagation
#   1.8  WCC connectivity components (GDS optional)
#   1.9  Debug inspection
#   1.10 Final validation
#
# GAP-9 FIX: Prerequisite check now requires PHASE0_COMPLETE (or IN_PROGRESS
#   as backward-compat for PIDs run before this fix). PHASE0_COMPLETE is the
#   status run_phase0.py writes on successful completion.
#   Previously run_phase0.py never wrote a completion status, so Phase 1 only
#   saw IN_PROGRESS and the PHASE0_COMPLETE entry in allowed_statuses was dead code.
#
# NEW-A + NEW-B: Steps 1.3b and 1.3c added after structural classification.
#   classify_equipment.infer_general_equipment_labels relabels small 'general'
#   float-coord degree-2 nodes to 'inferred_check_valve'.
#   classify_equipment.resolve_tank_functional_role stamps functional_label='pump'
#   on small 'tank' nodes, enabling correct engineering rule lookup in Phase 3.5.

import argparse
import os
import sys
import yaml
from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.parse_graphml   import parse_graphml
from engine.phase0_ingestion.normalize_nodes  import normalize_nodes
from engine.phase0_ingestion.load_to_neo4j   import Neo4jLoader

from engine.phase1_segmentation.group_connected_edges        import group_connected_edges
from engine.phase1_segmentation.create_pipe_segments         import create_pipe_segments
from engine.phase1_segmentation.collapse_to_symbol_segments  import collapse_symbol_paths
from engine.phase1_segmentation.classify_nodes               import classify_nodes_structurally
from engine.phase1_segmentation.classify_equipment           import (   # NEW-A + NEW-B
    infer_general_equipment_labels,
    resolve_tank_functional_role,
)
from engine.phase1_segmentation.validate_segments            import validate_pipe_segments

FORBIDDEN_PHASE1_LABELS = {"Flow", "Equipment", "Nozzle", "Interface"}
SAMPLE_SEGMENTS = 5


def load_configs():
    # Only loads storage config — Neo4jLoader() handles its own credential
    # resolution (config/neo4j.yaml → env var overrides: NEO4J_URI/USER/PASSWORD).
    storage_cfg_path = os.path.join(PROJECT_ROOT, "config", "storage.yaml")
    with open(storage_cfg_path, "r") as f:
        storage_cfg = yaml.safe_load(f)["storage"]
    return storage_cfg


def check_pid_status(loader, pid_id):
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) RETURN pid.status AS status",
            pid_id=pid_id,
        ).single()
    return row["status"] if row else None


def clear_phase1_data(loader, pid_id):
    """Remove Phase 1 data only (PS + LPS). Node/AnnotationRequest preserved."""
    with loader.driver.session(database=loader.database) as s:
        s.run("MATCH (l:LogicalPipeSegment {pid_id: $pid_id}) DETACH DELETE l", pid_id=pid_id)
        s.run("MATCH (ps:PipeSegment {pid_id: $pid_id}) DETACH DELETE ps", pid_id=pid_id)
        s.run(
            "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE0_COMPLETE'",
            pid_id=pid_id,
        )
    print(f"[PHASE 1] Cleared PipeSegments and LogicalPipeSegments for PID={pid_id}")


def resolve_pid_paths(loader, pid_id, store_root):
    with loader.driver.session(database=loader.database) as s:
        row = s.run(
            """
            MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)-[:HAS_PID]->(pid:PID {pid_id: $pid_id})
            RETURN pid.graphml_path AS graphml_rel,
                   pid.image_path   AS image_rel,
                   skid.skid_id     AS skid_id,
                   skid.skid_type   AS skid_type,
                   plant.plant_id   AS plant_id
            """,
            pid_id=pid_id,
        ).single()

    if row is None:
        raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

    graphml_abs = os.path.join(store_root, row["graphml_rel"].replace("/", os.sep))
    image_abs   = os.path.join(store_root, row["image_rel"].replace("/", os.sep))

    if not os.path.exists(graphml_abs):
        raise FileNotFoundError(f"GraphML not found: {graphml_abs}")
    if not os.path.exists(image_abs):
        raise FileNotFoundError(f"Image not found: {image_abs}")

    print(f"[PHASE 1] PID resolved: Plant={row['plant_id']} Skid={row['skid_id']} PID={pid_id}")
    return {
        "graphml_path": graphml_abs,
        "image_path":   image_abs,
        "plant_id":     row["plant_id"],
        "skid_id":      row["skid_id"],
        "skid_type":    row["skid_type"],
    }


def assert_phase1_constraints(session):
    result = session.run(
        """
        MATCH (n)
        WHERE any(lbl IN labels(n) WHERE lbl IN $forbidden)
        RETURN collect(DISTINCT labels(n)) AS violations
        """,
        forbidden=list(FORBIDDEN_PHASE1_LABELS),
    )
    record = result.single()
    if record and record["violations"]:
        raise RuntimeError(
            f"[PHASE 1 VIOLATION] Semantic labels detected: {record['violations']}"
        )


def create_indexes(tx):
    queries = [
        "CREATE INDEX IF NOT EXISTS FOR (n:Node) ON (n.id)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Node) ON (n.pid_id)",
        "CREATE INDEX IF NOT EXISTS FOR (ps:PipeSegment) ON (ps.id)",
        "CREATE INDEX IF NOT EXISTS FOR (ps:PipeSegment) ON (ps.pid_id)",
        "CREATE INDEX IF NOT EXISTS FOR (l:LogicalPipeSegment) ON (l.id)",
        "CREATE INDEX IF NOT EXISTS FOR (l:LogicalPipeSegment) ON (l.pid_id)",
    ]
    for q in queries:
        tx.run(q)


def create_pipe_endpoints(tx):
    result = tx.run(
        """
        MATCH (n:Node)-[:ENDPOINT_OF]->(l:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment)
        MERGE (ps)-[r:ENDPOINT_OF]->(n)
        ON CREATE SET
            r.source        = 'derived_from_logical',
            r.endpoint_type = 'structural',
            r.created_at    = timestamp()
        RETURN count(r) AS endpoints_created
        """
    )
    rec = result.single()
    return rec["endpoints_created"] if rec else 0


def derive_pipe_endpoints_from_degree(tx):
    result = tx.run(
        """
        MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node)
        WITH ps, n
        MATCH (n)-[:PIPE]-(m:Node)
        WHERE (ps)-[:CONTAINS]->(m)
        WITH ps, n, count(m) AS internal_degree
        WHERE internal_degree = 1
        MERGE (ps)-[r:ENDPOINT_OF]->(n)
        ON CREATE SET r.source = 'derived_from_degree', r.created_at = timestamp()
        RETURN count(r) AS endpoints_created
        """
    )
    rec = result.single()
    return rec["endpoints_created"] if rec else 0


def verify_lps_adjacency(session, pid_id):
    row = session.run(
        """
        MATCH ()-[r:ADJACENT_VIA_NODES]-()
        MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
        RETURN count(DISTINCT r) AS adj_count,
               count(DISTINCT lps) AS lps_count
        """,
        pid_id=pid_id,
    ).single()

    adj_count = int(row["adj_count"]) if row else 0
    lps_count = int(row["lps_count"]) if row else 0

    if adj_count == 0 and lps_count > 0:
        raise RuntimeError(
            f"[PHASE 1] CRITICAL: 0 ADJACENT_VIA_NODES edges for {lps_count} LPS in "
            f"PID={pid_id}. Phase 4 FSM cannot run without LPS adjacency. "
            "Check collapse_to_symbol_segments FIX-6."
        )
    print(f"[PHASE 1] LPS adjacency verified: {adj_count} ADJACENT_VIA_NODES edges for {lps_count} LPS")


def persist_ps_components(tx):
    try:
        tx.run(
            """
            CALL gds.graph.project(
                'psGraph', 'PipeSegment',
                {
                    ADJACENT_VIA_NODES: {type: 'ADJACENT_VIA_NODES', orientation: 'UNDIRECTED'},
                    JOINS_AT:           {type: 'JOINS_AT',           orientation: 'UNDIRECTED'}
                }
            )
            """
        )
        result = tx.run(
            """
            CALL gds.wcc.stream('psGraph')
            YIELD nodeId, componentId
            WITH gds.util.asNode(nodeId) AS ps, componentId
            SET ps.component_id = componentId
            RETURN componentId, count(*) AS size
            ORDER BY size DESC
            """
        )
        components = [{"componentId": r["componentId"], "size": r["size"]} for r in result]
        try:
            tx.run("CALL gds.graph.drop('psGraph', false)")
        except Exception:
            pass
        return components
    except Exception as e:
        print(f"[WARN] GDS WCC skipped (plugin not available or error): {e}")
        return []


def debug_segments(session, sample_count=5):
    print(f"[DEBUG] Inspecting {sample_count} PipeSegments")
    result = session.run(
        """
        MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node)
        WITH ps, collect(n.id) AS node_ids
        ORDER BY ps.id
        LIMIT $limit
        RETURN ps.id AS ps_id, node_ids
        """,
        limit=sample_count,
    )
    for record in result:
        print(f"[DEBUG] {record['ps_id']} contains nodes: {record['node_ids']}")


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 structural reconstruction.")
    parser.add_argument("--pid",   required=True,       help="PID ID as registered in Neo4j")
    parser.add_argument("--force", action="store_true", help="Skip re-ingestion prompt")
    args = parser.parse_args()
    pid_id = args.pid

    print(f"========== PHASE 1 START | PID={pid_id} ==========")

    storage_cfg = load_configs()
    store_root = storage_cfg["store_root"]
    # Neo4jLoader() resolves credentials itself: config/neo4j.yaml then env vars
    # (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) — no YAML read needed here.
    loader = Neo4jLoader()

    try:
        # ── GAP-9: Updated prerequisite check ─────────────────────────────
        # PHASE0_COMPLETE is the canonical prerequisite status.
        # IN_PROGRESS is accepted as backward compat for PIDs ingested before
        # this fix (run_phase0.py previously never wrote PHASE0_COMPLETE).
        already_ingested_statuses = {
            "PHASE1_COMPLETE",
            "PHASE2_COMPLETE",
            "PHASE3_COMPLETE",
            "PHASE4_COMPLETE",
            "PHASE5_COMPLETE",
            "PHASE6_COMPLETE",
            "PHASE7_COMPLETE",
        }
        valid_prereq_statuses = {"PHASE0_COMPLETE", "IN_PROGRESS"}

        current_status = check_pid_status(loader, pid_id)

        if current_status is None:
            raise ValueError(f"PID '{pid_id}' not found. Run register_pid.py first.")

        if current_status == "REGISTERED":
            raise RuntimeError(
                f"[PHASE 1] PID '{pid_id}' has status=REGISTERED. "
                f"Phase 0 has not been run yet.\n"
                f"  Run: python scripts/run_phase0.py --pid {pid_id}"
            )

        if current_status not in valid_prereq_statuses | already_ingested_statuses:
            raise ValueError(f"PID '{pid_id}' has unexpected status: '{current_status}'")

        if current_status in already_ingested_statuses:
            print(
                f"\n[PHASE 1] WARNING: PID={pid_id} already has status='{current_status}'.\n"
                f"  Re-running will clear PipeSegment and LogicalPipeSegment data.\n"
                f"  Phase 0 Node and AnnotationRequest data is preserved.\n"
            )
            if args.force:
                print("[PHASE 1] --force flag set. Clearing and re-running.")
                proceed = True
            else:
                answer = input("  Proceed with re-run? [y/N]: ").strip().lower()
                proceed = answer == "y"

            if not proceed:
                print("[PHASE 1] Aborted. No changes made.")
                loader.close()
                return

            clear_phase1_data(loader, pid_id)

        # ── Resolve paths ─────────────────────────────────────────────────
        ctx = resolve_pid_paths(loader, pid_id, store_root)

        # ── 1.0 Parse + Normalize ─────────────────────────────────────────
        nodes, edges = parse_graphml(ctx["graphml_path"])
        print(f"[INFO] Parsed nodes={len(nodes)} edges={len(edges)}")
        nodes = normalize_nodes(nodes)

        # ── 1.1 Group edges → PipeSegments ───────────────────────────────
        segments = group_connected_edges(nodes, edges)
        print(f"[INFO] Identified {len(segments)} PipeSegments")

        # ── 1.2 Persist PipeSegments ──────────────────────────────────────
        create_pipe_segments(segments, nodes, loader, pid_id=pid_id)

        with loader.driver.session(database=loader.database) as session:
            session.execute_write(create_indexes)
            assert_phase1_constraints(session)
            print("[INFO] Phase 1 constraints verified")

        # ── 1.3 Structural classification ─────────────────────────────────
        try:
            with Image.open(ctx["image_path"]) as img:
                image_width, image_height = img.size
        except Exception:
            image_width, image_height = 10000, 10000

        classify_nodes_structurally(
            loader.driver, loader.database, image_width, image_height,
            pid_id=pid_id,
        )

        # ── 1.3b NEW-B: General label inference ───────────────────────────
        # Relabels small 'general' float-coord degree-2 nodes to
        # 'inferred_check_valve' so Phase 3 engineering rules can validate them.
        infer_general_equipment_labels(
            loader.driver, loader.database, pid_id=pid_id,
        )

        # ── 1.3c NEW-A: Tank functional role resolution ───────────────────
        # Stamps functional_label='pump' on small 'tank' nodes (width < 100px).
        # Phase 3.5 engineering_rules.py reads functional_label for rule lookup.
        resolve_tank_functional_role(
            loader.driver, loader.database, pid_id=pid_id,
        )

        # ── 1.4 Pre-collapse validation ───────────────────────────────────
        validate_pipe_segments(loader.driver, pid_id=pid_id, database=loader.database)

        # ── 1.5 Logical collapse + LPS adjacency ──────────────────────────
        collapse_symbol_paths(
            loader.driver, loader.database,
            pid_id=pid_id, max_hops=12, path_limit=1000,
        )

        # ── 1.6 Verify LPS adjacency ──────────────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            verify_lps_adjacency(session, pid_id)

        # ── 1.7 PS endpoint propagation ───────────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            ep1 = session.execute_write(create_pipe_endpoints)
            ep2 = session.execute_write(derive_pipe_endpoints_from_degree)
            print(f"[INFO] PS Endpoints: logical={ep1}, degree={ep2}")

        # ── 1.8 WCC components (GDS optional) ────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            components = session.execute_write(persist_ps_components)
            if components:
                print("[INFO] WCC components (top 5):")
                for c in components[:5]:
                    print(f"  Component {c['componentId']} → size {c['size']}")
            else:
                print("[INFO] WCC components: skipped (GDS not available)")

        # ── 1.9 Debug inspection ──────────────────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            debug_segments(session, SAMPLE_SEGMENTS)

        # ── 1.10 Final validation ─────────────────────────────────────────
        validate_pipe_segments(loader.driver, pid_id=pid_id, database=loader.database)

        # ── Update PID status ─────────────────────────────────────────────
        with loader.driver.session(database=loader.database) as session:
            session.run(
                "MATCH (pid:PID {pid_id: $pid_id}) SET pid.status = 'PHASE1_COMPLETE'",
                pid_id=pid_id,
            )

        print(f"[INFO] PHASE 1 COMPLETE — structural graph locked | PID={pid_id}")

    finally:
        loader.close()

    print(f"========== PHASE 1 END | PID={pid_id} ==========")


if __name__ == "__main__":
    main()