# tests/verify_phase1_debug.py
#
# Phase 1 integrity and debug verification (READ-ONLY).
#
# Changes from pid_kos version:
#   - from ingestion.load_to_neo4j → from engine.phase0_ingestion.load_to_neo4j
#   - Neo4jLoader takes neo4j_cfg dict (loaded from config/neo4j.yaml)
#   - database: 'kos' → 'engine' (via config)
#   - [:CONNECTED] → [:PIPE] throughout all Cypher queries

import os
import sys
import yaml
from typing import Optional, Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from neo4j.exceptions import Neo4jError


def fail(msg: str):
    raise RuntimeError(f"[PHASE 1 VERIFY FAIL] {msg}")

def info(msg: str):
    print(f"[VERIFY] {msg}")

def warn(msg: str):
    print(f"[WARN] {msg}")

def header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def safe_single_value(
    session, query: str,
    params: Optional[Dict[str, Any]] = None,
    key: str = "c",
) -> int:
    try:
        record = session.run(query, params or {}).single()
        if record:
            value = record.get(key)
            return int(value) if value is not None else 0
        return 0
    except Neo4jError as e:
        print(f"[ERROR] Query failed: {e}")
        raise

def safe_list(
    session, query: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    try:
        return session.run(query, params or {}).data()
    except Neo4jError as e:
        print(f"[ERROR] Query failed: {e}")
        raise


def main():
    print("========== PHASE 1 VERIFICATION + DEBUG START ==========")

    neo4j_cfg_path = os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")
    with open(neo4j_cfg_path, "r") as f:
        neo4j_cfg = yaml.safe_load(f)["neo4j"]

    loader = Neo4jLoader(neo4j_cfg)

    try:
        with loader.driver.session(database=loader.database) as session:

            # ── 0. Initial PipeSegment sanity ─────────────────────────────
            header("0. INITIAL DEBUG — PIPESEGMENT CHECK")
            debug_rows = session.run(
                "MATCH (ps:PipeSegment) RETURN ps.id AS id, ps.source AS src LIMIT 10"
            ).data()
            print("[DEBUG] First 10 PipeSegments:", debug_rows)
            if not debug_rows:
                warn("No PipeSegment nodes returned!")

            # ── 1. Existence & basic integrity ────────────────────────────
            header("1. PIPESEGMENT EXISTENCE & BASIC INTEGRITY")
            ps_count = safe_single_value(
                session, "MATCH (ps:PipeSegment) RETURN count(ps) AS c"
            )
            info(f"PipeSegments present: {ps_count}")
            if ps_count == 0:
                fail("No PipeSegment nodes found")

            empty_ps = safe_single_value(
                session,
                """
                MATCH (ps:PipeSegment)
                WHERE NOT (ps)-[:CONTAINS]->(:Node)
                RETURN count(ps) AS c
                """,
            )
            info(f"PipeSegments with NO contained nodes: {empty_ps}")
            if empty_ps > 0:
                fail(f"{empty_ps} PipeSegments have NO contained nodes")

            rows = safe_list(session, """
                MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node)
                WITH ps, collect(n.id) AS nodes
                ORDER BY size(nodes) DESC
                LIMIT 5
                RETURN ps.id AS ps_id, size(nodes) AS cnt, nodes
            """)
            print("\n[DEBUG] Sample PipeSegments (largest first):")
            for r in rows:
                print(f"  {r['ps_id']} | nodes={r['cnt']} | sample={r['nodes'][:6]}")

            # ── 2. PIPE graph consistency (was CONNECTED) ──────────────────
            header("2. PIPE GRAPH CONSISTENCY")
            # PIPE is undirected — symmetry check via direction is not applicable.
            # Instead verify no isolated node still has CONNECTED (old relationship).
            old_connected = safe_single_value(
                session,
                "MATCH ()-[r:CONNECTED]-() RETURN count(r) AS c",
            )
            info(f"Legacy CONNECTED relationships remaining: {old_connected}")
            if old_connected > 0:
                warn(
                    f"{old_connected} CONNECTED relationships still exist. "
                    "Phase 0 should only write PIPE."
                )

            high_deg = safe_list(session, """
                MATCH (n:Node)-[:PIPE]-(m)
                WITH n, count(m) AS deg
                ORDER BY deg DESC
                LIMIT 12
                RETURN n.id AS id, n.structural_type AS type, deg
            """)
            print("\n[DEBUG] High-degree nodes (junction candidates):")
            for r in high_deg:
                print(f"  {r['id']} | type={r['type']} | degree={r['deg']}")

            # ── 3. Forbidden structural conditions ─────────────────────────
            header("3. FORBIDDEN STRUCTURAL CONDITIONS")
            ps_adj = safe_single_value(
                session,
                "MATCH (ps1:PipeSegment)-[:PIPE]-(ps2:PipeSegment) RETURN count(*) AS c",
            )
            info(f"PipeSegment↔PipeSegment PIPE adjacency: {ps_adj}")
            if ps_adj > 0:
                fail("PipeSegment ↔ PipeSegment PIPE adjacency detected")

            # ── 4. Structural classification coverage ──────────────────────
            header("4. STRUCTURAL CLASSIFICATION COVERAGE")
            unclassified = safe_single_value(
                session,
                "MATCH (n:Node) WHERE n.structural_type IS NULL RETURN count(n) AS c",
            )
            info(f"Unclassified nodes: {unclassified}")
            if unclassified > 0:
                rows = safe_list(session, """
                    MATCH (n:Node) WHERE n.structural_type IS NULL
                    RETURN n.id AS id, n.label AS label LIMIT 20
                """)
                for r in rows:
                    print(f"  {r['id']} | label={r['label']}")
                fail(f"{unclassified} nodes missing structural_type")

            # ── 5. Geometric data check ────────────────────────────────────
            header("5. GEOMETRIC DATA CHECK")
            bbox_missing = safe_single_value(session, """
                MATCH (n:Node)
                WHERE n.xmin IS NULL OR n.ymin IS NULL OR n.xmax IS NULL OR n.ymax IS NULL
                RETURN count(n) AS c
            """)
            info(f"Nodes missing bounding boxes: {bbox_missing}")
            if bbox_missing > 0:
                fail(f"{bbox_missing} nodes missing bounding boxes")

            # ── 7. Provenance check ───────────────────────────────────────
            header("7. PROVENANCE CHECK")
            bad_source = safe_single_value(session, """
                MATCH (n)
                WHERE (n:Node        AND n.source <> 'graphml')
                   OR (n:PipeSegment AND n.source <> 'derived')
                RETURN count(n) AS c
            """)
            info(f"Nodes/PipeSegments with bad source: {bad_source}")
            if bad_source > 0:
                fail("Invalid source detected")

            # ── 8. ADJACENT_VIA_NODES check ───────────────────────────────
            header("8. ADJACENCY GRAPH")
            adj_count = safe_single_value(
                session,
                "MATCH ()-[r:ADJACENT_VIA_NODES]-() RETURN count(r) AS c",
            )
            info(f"ADJACENT_VIA_NODES relationships: {adj_count}")
            if adj_count > 0:
                adj_samples = safe_list(session, """
                    MATCH (a:PipeSegment)-[r:ADJACENT_VIA_NODES]-(b:PipeSegment)
                    RETURN a.id AS a, b.id AS b, r.via_count AS via_count, r.via_nodes AS via_nodes
                    ORDER BY r.via_count DESC
                    LIMIT 20
                """)
                print("\n[DEBUG] Sample ADJACENT_VIA_NODES (top via_count):")
                for r in adj_samples:
                    print(f"  {r['a']} <-> {r['b']} | via_count={r['via_count']} | sample={(r['via_nodes'] or [])[:6]}")

                mismatch_adj = safe_single_value(session, """
                    MATCH ()-[r:ADJACENT_VIA_NODES]-()
                    WHERE r.via_count <> size(r.via_nodes)
                    RETURN count(r) AS c
                """)
                if mismatch_adj > 0:
                    warn(f"{mismatch_adj} ADJACENT_VIA_NODES have via_count != size(via_nodes)")

            # ── 9. Internal connectivity ───────────────────────────────────
            header("9. INTERNAL CONNECTIVITY PER PIPESEGMENT")
            disconnected_ps = safe_list(session, """
                MATCH (ps:PipeSegment)-[:ENDPOINT_OF]->(n:Node)
                WITH ps, collect(n.id) AS nodes
                WHERE size(nodes) > 0
                UNWIND nodes AS seed
                WITH ps, seed, nodes
                MATCH (seedNode:Node {id: seed})
                MATCH (seedNode)-[:PIPE*0..20]-(m:Node)
                WITH ps, nodes, collect(DISTINCT m.id) AS reachable
                WITH ps, size(nodes) AS total_nodes,
                     size([x IN reachable WHERE x IN nodes]) AS reachable_in_ps
                WHERE reachable_in_ps <> total_nodes
                RETURN ps.id AS ps_id, total_nodes, reachable_in_ps
                LIMIT 200
            """)
            if disconnected_ps:
                warn(f"{len(disconnected_ps)} PipeSegments with internal disconnected nodes:")
                for r in disconnected_ps[:20]:
                    print(f"  {r['ps_id']} | declared={r['total_nodes']} | reachable={r['reachable_in_ps']}")
            else:
                info("All PipeSegments pass internal connectivity check")

            # ── 10. Endpoint count consistency ────────────────────────────
            header("10. ENDPOINTS: node_count vs ENDPOINT_OF")
            mismatch_counts = safe_list(session, """
                MATCH (ps:PipeSegment)
                OPTIONAL MATCH (ps)-[:ENDPOINT_OF]->(n:Node)
                WITH ps, ps.node_count AS declared, count(DISTINCT n) AS endpoints_found
                WHERE declared IS NOT NULL AND declared <> endpoints_found
                RETURN ps.id AS ps_id, declared, endpoints_found
                LIMIT 200
            """)
            if mismatch_counts:
                warn(f"{len(mismatch_counts)} PipeSegments where node_count != ENDPOINT_OF count:")
                for r in mismatch_counts[:20]:
                    print(f"  {r['ps_id']} | declared={r['declared']} | found={r['endpoints_found']}")
            else:
                info("node_count matches ENDPOINT_OF counts")

            # ── 11. Logical pipe segment coverage ─────────────────────────
            header("11. LOGICAL PIPE SEGMENTS COVERAGE")
            logical_count = safe_single_value(
                session, "MATCH (l:LogicalPipeSegment) RETURN count(l) AS c"
            )
            info(f"LogicalPipeSegment count: {logical_count}")

            ps_covered = safe_single_value(session, """
                MATCH (l:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment)
                RETURN count(DISTINCT ps) AS c
            """)
            logical_covered = safe_single_value(session, """
                MATCH (l:LogicalPipeSegment)-[:COVERS]->(ps:PipeSegment)
                RETURN count(DISTINCT l) AS c
            """)
            info(f"PipeSegments covered: {ps_covered} | LogicalPipeSegments with COVERS: {logical_covered}")

            covers_samples = safe_list(session, """
                MATCH (l:LogicalPipeSegment)-[c:COVERS]->(ps:PipeSegment)
                RETURN l.id AS logical, ps.id AS ps,
                       c.via_node AS via_node, l.trace_nodes AS trace_nodes
                LIMIT 30
            """)
            if covers_samples:
                print("\n[DEBUG] Sample COVERS (Logical → PipeSegment):")
                for r in covers_samples:
                    print(f"  {r['logical']} → {r['ps']} | via_node={r.get('via_node')} | trace={(r.get('trace_nodes') or [])[:6]}")

            # ── 12. Graph property consistency ────────────────────────────
            header("12. GRAPH PROPERTY CONSISTENCY")
            missing_geom = safe_single_value(
                session,
                "MATCH (ps:PipeSegment) WHERE ps.geometry_hash IS NULL RETURN count(ps) AS c",
            )
            info(f"PipeSegments missing geometry_hash: {missing_geom}")

            bad_nodecount = safe_list(session, """
                MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node)
                WITH ps, collect(n) AS nodes
                WHERE ps.node_count IS NOT NULL AND ps.node_count <> size(nodes)
                RETURN ps.id AS ps_id, ps.node_count AS declared, size(nodes) AS actual
                LIMIT 50
            """)
            if bad_nodecount:
                warn(f"{len(bad_nodecount)} PipeSegments node_count mismatch:")
                for r in bad_nodecount[:20]:
                    print(f"  {r['ps_id']} declared={r['declared']} actual={r['actual']}")
            else:
                info("ps.node_count matches actual CONTAINS sizes")

            # ── 13. Orphan nodes ──────────────────────────────────────────
            header("13. ORPHAN NODES")
            orphan_nodes = safe_list(session, """
                MATCH (n:Node)
                WHERE NOT (
                    (n)<-[:CONTAINS]-(:PipeSegment)
                    OR (n)<-[:ENDPOINT_OF]-(:PipeSegment)
                    OR (n)-[:PIPE]-(:Node)
                )
                RETURN n.id AS id, n.label AS label,
                       n.structural_type AS structural_type,
                       COUNT { (n)-[:PIPE]-() } AS degree
                LIMIT 200
            """)
            info(f"Orphan nodes (no PS involvement, no PIPE links): {len(orphan_nodes)}")
            expected_labels = {"background", "label", "annotation"}
            suspicious = [
                r for r in orphan_nodes
                if (r.get("label") or "").lower() not in expected_labels
                and (r.get("structural_type") or "").lower() not in expected_labels
            ]
            for r in orphan_nodes[:30]:
                print(f"  {r['id']} | label={r['label']} | structural_type={r['structural_type']}")
            if suspicious:
                warn(f"{len(suspicious)} suspicious orphan nodes (not background/label)")

            # ── 14. Summary ───────────────────────────────────────────────
            header("14. QUICK SUMMARY METRICS")
            metrics = safe_list(session, """
                MATCH (ps:PipeSegment)
                WITH count(ps) AS ps_count
                MATCH (l:LogicalPipeSegment)
                WITH ps_count, count(l) AS logical_count
                RETURN ps_count, logical_count
            """)
            if metrics:
                m = metrics[0]
                info(f"PipeSegments={m['ps_count']}, LogicalPipeSegments={m['logical_count']}")

            print("\n[INFO] Phase 1 verification complete.")

    finally:
        loader.close()

    print("\n========== PHASE 1 VERIFICATION + DEBUG COMPLETE ==========")


if __name__ == "__main__":
    main()