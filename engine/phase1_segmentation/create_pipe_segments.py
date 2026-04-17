# engine/phase1_segmentation/create_pipe_segments.py
#
# Creation of PipeSegments + JOINS_AT relations.
#
# Changes from pid_kos version:
#   - from ingestion.load_to_neo4j → from engine.phase0_ingestion.load_to_neo4j
#   - loader accepts neo4j_cfg dict (caller passes it in)
#   - [:CONNECTED] → [:PIPE] throughout
#   - database default: implicit 'kos' → explicit from loader
#
# FIX-4: pid_id is now stamped on every PipeSegment node (both MERGE key
#         and SET property). Prevents orphaned PS nodes with no pid_id
#         when CONTAINS relationships are lost on a bad re-run.
#         Function signature updated: pid_id is now a required argument.

import hashlib
import time

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader

MAX_DEBUG_ITEMS = 10
MULTIHOP_CHUNK  = 750


def hash_geometry(node_ids, nodes_dict):
    """Stable MD5 hash of bounding boxes for a node set."""
    coords = []
    for nid in node_ids:
        n = nodes_dict.get(nid)
        if not n:
            coords.append(f"missing:{nid}")
            continue
        a = n.get("attrs", {})
        coords.append(
            f"{a.get('xmin', 0)}:{a.get('ymin', 0)}:{a.get('xmax', 0)}:{a.get('ymax', 0)}"
        )
    return hashlib.md5("|".join(sorted(coords)).encode()).hexdigest()


def create_pipe_segments(segments, nodes, loader, pid_id, verbose=True):
    """
    Create PipeSegments and JOINS_AT relations.

    Args:
        segments: list of node-id lists from group_connected_edges
        nodes:    list of node dicts from normalize_nodes
        loader:   Neo4jLoader instance (caller owns creation + close)
        pid_id:   PID identifier — stamped on every PipeSegment node (FIX-4)
        verbose:  print debug steps

    Returns: summary dict with counts and timings.
    """
    nodes_dict = {n["id"]: n for n in nodes}
    debug      = {"contains": 0, "shared": 0, "direct": 0, "twohop": 0}
    timings    = {}

    with loader.driver.session(database=loader.database) as session:
        t0 = time.perf_counter()
        if verbose:
            print(f"[DEBUG] Creating {len(segments)} PipeSegments for PID={pid_id}")

        # ── STEP 0: CREATE PipeSegments + CONTAINS ────────────────────────
        t_step = time.perf_counter()
        for i, node_ids in enumerate(segments):
            ps_id     = f"PS_{i + 1}"
            geom_hash = hash_geometry(node_ids, nodes_dict)

            # FIX-4: pid_id included in MERGE key and SET
            session.run(
                """
                MERGE (ps:PipeSegment {id: $id, pid_id: $pid_id})
                ON CREATE SET ps.geometry_hash = $hash,
                              ps.source        = 'derived',
                              ps.pid_id        = $pid_id
                ON MATCH SET  ps.geometry_hash = $hash
                """,
                {"id": ps_id, "pid_id": pid_id, "hash": geom_hash},
            )

            present = [nid for nid in node_ids if nid in nodes_dict]
            if present:
                session.run(
                    """
                    MATCH (ps:PipeSegment {id: $pid, pid_id: $pid_id})
                    UNWIND $nids AS nid
                    MATCH (n:Node {id: nid, pid_id: $pid_id})
                    MERGE (ps)-[:CONTAINS]->(n)
                    """,
                    {"pid": ps_id, "pid_id": pid_id, "nids": present},
                )
                debug["contains"] += 1
            else:
                print(f"[WARN] PS {ps_id} has 0 present nodes (all missing from input)")

        timings["create_ps_contains"] = time.perf_counter() - t_step

        # ── STEP 1: SHARED NODE JOINS ─────────────────────────────────────
        t_step = time.perf_counter()
        if verbose:
            print("[DEBUG] Step 1 — shared node joins")
        session.run(
            """
            MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node)<-[:CONTAINS]-(ps2:PipeSegment {pid_id: $pid_id})
            WHERE ps1.id < ps2.id
            MERGE (ps1)-[r:JOINS_AT]->(ps2)
            ON CREATE SET r.kind = 'shared_node', r.trace_nodes = [n.id]
            ON MATCH  SET r.trace_nodes = coalesce(r.trace_nodes, []) + n.id
            """,
            {"pid_id": pid_id},
        )
        timings["shared_node"] = time.perf_counter() - t_step

        # ── STEP 2: DIRECT PIPE-CONNECTED NODE JOINS ──────────────────────
        t_step = time.perf_counter()
        if verbose:
            print("[DEBUG] Step 2 — direct connectivity")
        session.run(
            """
            MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n1:Node)-[:PIPE]-(n2:Node)<-[:CONTAINS]-(ps2:PipeSegment {pid_id: $pid_id})
            WHERE ps1.id < ps2.id
            MERGE (ps1)-[r:JOINS_AT]->(ps2)
            ON CREATE SET r.kind = 'direct_connected', r.trace_nodes = [n1.id, n2.id]
            ON MATCH  SET r.trace_nodes = coalesce(r.trace_nodes, []) + n1.id + n2.id
            """,
            {"pid_id": pid_id},
        )
        timings["direct_connected"] = time.perf_counter() - t_step

        # ── STEP 3: TWO-HOP NODE JOINS ────────────────────────────────────
        t_step = time.perf_counter()
        if verbose:
            print("[DEBUG] Step 3 — two-hop connectivity")
        session.run(
            """
            MATCH (ps1:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n1:Node)-[:PIPE]-(mid:Node)-[:PIPE]-(n2:Node)<-[:CONTAINS]-(ps2:PipeSegment {pid_id: $pid_id})
            WHERE ps1.id < ps2.id
            MERGE (ps1)-[r:JOINS_AT]->(ps2)
            ON CREATE SET r.kind = 'two_hop', r.trace_nodes = [n1.id, mid.id, n2.id]
            ON MATCH  SET r.trace_nodes = coalesce(r.trace_nodes, []) + n1.id + mid.id + n2.id
            """,
            {"pid_id": pid_id},
        )
        timings["two_hop"] = time.perf_counter() - t_step

        # ── FINAL COUNTS ──────────────────────────────────────────────────
        t_final = time.perf_counter()
        counts = session.run(
            """
            MATCH (ps1:PipeSegment {pid_id: $pid_id})-[r:JOINS_AT]->(ps2:PipeSegment {pid_id: $pid_id})
            RETURN r.kind AS kind, count(r) AS cnt
            ORDER BY cnt DESC
            """,
            pid_id=pid_id,
        ).data()
        counts_map = {r["kind"]: r["cnt"] for r in counts}
        timings["final_count_query"] = time.perf_counter() - t_final

        # Populate debug from the pid-scoped final counts (avoids unscoped
        # intermediate queries that trigger schema warnings on a fresh DB).
        debug["shared"] = counts_map.get("shared_node", 0)
        debug["direct"] = counts_map.get("direct_connected", 0)
        debug["twohop"] = counts_map.get("two_hop", 0)

        total_time = time.perf_counter() - t0

        summary = {
            "counts_by_kind": counts_map,
            "debug": debug,
            "timings": timings,
            "total_time_s": total_time,
        }

        print("===================================================")
        for kind, cnt in counts_map.items():
            print(f"[SUMMARY] {kind:20s}: {cnt}")
        print(f"[TIMING] total_time_s          : {summary['total_time_s']:.2f}s")
        for k, v in timings.items():
            print(f"[TIMING] {k:22s}: {v:.2f}s")
        print("===================================================")

        return summary