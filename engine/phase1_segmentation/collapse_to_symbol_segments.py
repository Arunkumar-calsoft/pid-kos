# engine/phase1_segmentation/collapse_to_symbol_segments.py
#
# Logical collapse of symbol-to-symbol paths into LogicalPipeSegment nodes.
#
# Changes from pid_kos version:
#   - [:CONNECTED] → [:PIPE] throughout
#   - database default: 'kos' → 'engine'
#
# FIX-5: pid_id is now stamped on every LogicalPipeSegment node (both
#         MERGE key and SET property). Prevents orphaned LPS nodes with
#         no pid_id when relationships are lost on a bad re-run.
#         Function signature updated: pid_id is now a required argument.
#
# FIX-6: ADJACENT_VIA_NODES is now written between LogicalPipeSegment nodes
#         (LPS↔LPS) at the end of collapse. Previously this relationship was
#         only written between PipeSegment nodes (PS↔PS) in run_phase1.py,
#         which meant the Phase 4 FSM traversal graph did not exist.
#         This is the critical fix enabling Phase 4.

from typing import List
from collections import deque


def collapse_symbol_paths(
    driver,
    database="chatbot",
    pid_id=None,
    max_hops=8,
    path_limit=500,
    per_symbol_limit=20,
    verbose=True,
):
    """
    BFS from each SYMBOL node. Finds all symbol-to-symbol paths through
    non-symbol connector/crossing nodes and persists them as LogicalPipeSegments.

    Args:
        driver:            Neo4j driver instance
        database:          Neo4j database name
        pid_id:            PID identifier — required, stamped on every LPS (FIX-5)
        max_hops:          Maximum path length in BFS
        path_limit:        Maximum total LPS to create
        per_symbol_limit:  Maximum LPS per source symbol
        verbose:           Print progress

    Returns: count of LogicalPipeSegments created this run.
    """

    if pid_id is None:
        raise ValueError("[LogicalCollapse] pid_id is required (FIX-5)")

    def log(msg):
        if verbose:
            print(msg)

    log(f"[LogicalCollapse] START (pid_id={pid_id}, max_hops={max_hops}, "
        f"path_limit={path_limit}, per_symbol_limit={per_symbol_limit})")

    # ── Step 1: fetch structural types and adjacency from DB ───────────────
    with driver.session(database=database) as session:
        # FIX-5: scope queries to pid_id
        res = session.run(
            "MATCH (n:Node {pid_id: $pid_id}) "
            "RETURN n.id AS id, coalesce(n.structural_type, 'UNKNOWN') AS st",
            pid_id=pid_id,
        ).data()
        structural = {r["id"]: r["st"] for r in res}

        res = session.run(
            "MATCH (n:Node {pid_id: $pid_id})-[:PIPE]-(m:Node {pid_id: $pid_id}) "
            "RETURN n.id AS id, collect(m.id) AS nbrs",
            pid_id=pid_id,
        ).data()
        adj = {r["id"]: r["nbrs"] for r in res}

        existing_lps = set(
            r["id"] for r in
            session.run(
                "MATCH (l:LogicalPipeSegment {pid_id: $pid_id}) RETURN l.id AS id",
                pid_id=pid_id,
            ).data()
        )

    for nid in structural:
        adj.setdefault(nid, [])

    symbols = sorted([nid for nid, st in structural.items() if st == "SYMBOL"])
    log(f"[LogicalCollapse] SYMBOL nodes discovered: {len(symbols)}")

    created     = 0
    created_set = set(existing_lps)

    def persist_logical_segment(sid: str, tid: str, via_nodes: List[str], trace_nodes: List[str]):
        nonlocal created
        lps_id = f"{sid}__{tid}"
        if lps_id in created_set:
            return False

        # FIX-5: pid_id included in MERGE key and SET
        cypher_primary = """
        MERGE (l:LogicalPipeSegment {id: $lps_id, pid_id: $pid_id})
        ON CREATE SET
          l.pid_id      = $pid_id,
          l.endpoints   = $endpoints,
          l.via         = $via,
          l.trace_nodes = $trace_nodes,
          l.length      = size($via),
          l.source      = 'derived_logical',
          l.created_at  = timestamp()
        WITH l
        MATCH (s:Node {id: $s, pid_id: $pid_id}), (t:Node {id: $t, pid_id: $pid_id})
        MERGE (s)-[:ENDPOINT_OF {source: 'derived_logical'}]->(l)
        MERGE (t)-[:ENDPOINT_OF {source: 'derived_logical'}]->(l)
        RETURN l.id AS lid
        """

        # Link LPS → PS via via_nodes
        cypher_link_via = """
        UNWIND $via AS vid
        MATCH (l:LogicalPipeSegment {id: $lps_id, pid_id: $pid_id})
        MATCH (ps:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node {id: vid})
        MERGE (l)-[:COVERS {via_node: vid, source: 'derived_logical'}]->(ps)
        RETURN count(distinct ps) AS linked_by_via
        """

        # Link LPS → PS via endpoint nodes
        cypher_link_endpoints = """
        MATCH (l:LogicalPipeSegment {id: $lps_id, pid_id: $pid_id})
        MATCH (l)<-[:ENDPOINT_OF]-(ep:Node)
        MATCH (ps:PipeSegment {pid_id: $pid_id})-[:ENDPOINT_OF]->(ep)
        MERGE (l)-[:COVERS {via_node: ep.id, source: 'endpoint_match'}]->(ps)
        RETURN count(distinct ps) AS linked_by_endpoints
        """

        try:
            with driver.session(database=database) as session:
                session.run(
                    cypher_primary,
                    {
                        "lps_id":      lps_id,
                        "pid_id":      pid_id,
                        "endpoints":   [sid, tid],
                        "via":         via_nodes,
                        "trace_nodes": trace_nodes,
                        "s":           sid,
                        "t":           tid,
                    },
                )
                if via_nodes:
                    try:
                        session.run(cypher_link_via, {"lps_id": lps_id, "pid_id": pid_id, "via": via_nodes})
                    except Exception:
                        pass
                try:
                    session.run(cypher_link_endpoints, {"lps_id": lps_id, "pid_id": pid_id})
                except Exception:
                    pass

            created_set.add(lps_id)
            created += 1
            log(
                f"[LogicalCollapse] Persisted {lps_id} "
                f"(via_nodes={len(via_nodes)}, trace_nodes={len(trace_nodes)})"
            )
            return True

        except Exception as ex:
            log(f"[ERROR][LogicalCollapse] Failed to persist {lps_id}: {ex}")
            return False

    total_symbols = len(symbols)
    for idx, s in enumerate(symbols):
        if created >= path_limit:
            break

        per_symbol_created = 0
        visited = {s}
        queue = deque(
            (nbr, [s, nbr])
            for nbr in adj.get(s, [])
            if structural.get(nbr) != "SYMBOL"
        )
        visited.update(
            nbr for nbr in adj.get(s, [])
            if structural.get(nbr) != "SYMBOL"
        )

        while queue and created < path_limit and per_symbol_created < per_symbol_limit:
            current, path = queue.popleft()
            if len(path) - 1 > max_hops:
                continue

            for nbr in adj.get(current, []):
                if nbr in path:
                    continue
                if structural.get(nbr) == "SYMBOL" and nbr != s:
                    full_path = path + [nbr]
                    via_nodes = full_path[1:-1]
                    if all(structural.get(v) != "SYMBOL" for v in via_nodes):
                        sid_ord, tid_ord = sorted([s, nbr])
                        if sid_ord != s:
                            continue
                        ok = persist_logical_segment(sid_ord, tid_ord, via_nodes, full_path)
                        if ok:
                            per_symbol_created += 1
                            if created >= path_limit or per_symbol_created >= per_symbol_limit:
                                break
                    continue

                if structural.get(nbr) != "SYMBOL" and nbr not in visited:
                    visited.add(nbr)
                    queue.append((nbr, path + [nbr]))

        log(
            f"[LogicalCollapse] Processed symbol {idx+1}/{total_symbols} ({s}) "
            f"=> created for this symbol: {per_symbol_created}"
        )

    log(f"[LogicalCollapse] COMPLETED. Total logical segments created: {created}")

    # ── FIX-6: Write LPS↔LPS ADJACENT_VIA_NODES ──────────────────────────
    # This is the traversal graph Phase 4 FSM requires.
    # Two LPS are adjacent if they share an endpoint node.
    # Previously this was only written as PS↔PS in run_phase1.py — wrong type.
    log(f"[LogicalCollapse] Writing LPS↔LPS ADJACENT_VIA_NODES for pid_id={pid_id}")

    with driver.session(database=database) as session:
        result = session.run(
            """
            MATCH (lps1:LogicalPipeSegment {pid_id: $pid_id})<-[:ENDPOINT_OF]-(n:Node)-[:ENDPOINT_OF]->(lps2:LogicalPipeSegment {pid_id: $pid_id})
            WHERE lps1.id < lps2.id
            WITH lps1, lps2, collect(DISTINCT n.id) AS via_nodes
            MERGE (lps1)-[r:ADJACENT_VIA_NODES]->(lps2)
            SET r.via_count = size(via_nodes),
                r.via_nodes = via_nodes
            RETURN count(r) AS adjacency_edges_created
            """,
            pid_id=pid_id,
        )
        rec = result.single()
        adj_created = rec["adjacency_edges_created"] if rec else 0

    log(f"[LogicalCollapse] LPS adjacency edges written: {adj_created}")

    return created