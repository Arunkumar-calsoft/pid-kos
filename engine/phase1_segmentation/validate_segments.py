# engine/phase1_segmentation/validate_segments.py
#
# Phase 1 structural validation of PipeSegments.
#
# Changes from pid_kos version:
#   - [:CONNECTED] → [:PIPE] throughout (Phase 0 now writes undirected PIPE)
#   - database default: 'kos' → 'engine'
#   - DIAGNOSTIC_CSV path: root → logs/diagnostic_pipe_segments.csv

import os
import time
import csv
from collections import defaultdict, deque

from neo4j import GraphDatabase

DIAGNOSTIC_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "diagnostic_pipe_segments.csv"
)


def validate_pipe_segments(
    driver,
    pid_id: str,
    database="chatbot",
    write_csv=True,
    csv_path=None,
    allow_ps_adjacency=False,
):
    if pid_id is None:
        raise ValueError("pid_id is required for validate_pipe_segments")
    if csv_path is None:
        csv_path = DIAGNOSTIC_CSV

    start_ts = time.time()

    summary = {
        "total_pipe_segments": 0,
        "orphan_nodes": 0,
        "nodes_in_multips": 0,
        "bypass_errors": 0,
        "internal_disconnected": 0,
        "dead_end": 0,
        "isolated": 0,
    }

    diagnostics = []

    def bfs_connected(component_nodes, node_adj, start):
        if start not in component_nodes:
            return set()
        q = deque([start])
        seen = {start}
        while q:
            n = q.popleft()
            for nb in node_adj.get(n, ()):
                if nb in component_nodes and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        return seen

    with driver.session(database=database) as session:

        # ── 1. Annotate PipeSegments ───────────────────────────────────────
        session.run("""
            MATCH (p:PipeSegment {pid_id: $pid_id})
            OPTIONAL MATCH (p)-[:CONTAINS]->(n:Node {pid_id: $pid_id})
            WITH p, count(n) AS node_count
            SET p.node_count = node_count,
                p.segment_status =
                    CASE
                        WHEN node_count >= 2 THEN 'NORMAL'
                        WHEN node_count = 1  THEN 'DEAD_END'
                        ELSE 'ISOLATED'
                    END
        """, pid_id=pid_id)

        # ── 2. PipeSegment → Nodes ─────────────────────────────────────────
        rows = session.run("""
            MATCH (ps:PipeSegment {pid_id: $pid_id})
            OPTIONAL MATCH (ps)-[:CONTAINS]->(n:Node {pid_id: $pid_id})
            RETURN ps.id AS ps_id, collect(n.id) AS node_ids
        """, pid_id=pid_id).data()

        ps_to_nodes = {
            r["ps_id"]: [nid for nid in r["node_ids"] if nid is not None]
            for r in rows
        }

        summary["total_pipe_segments"] = len(ps_to_nodes)
        for nodes in ps_to_nodes.values():
            if len(nodes) == 1:
                summary["dead_end"] += 1
            elif len(nodes) == 0:
                summary["isolated"] += 1

        # ── 3. Node → PipeSegments ─────────────────────────────────────────
        node_to_ps = defaultdict(list)
        for ps, nodes in ps_to_nodes.items():
            for n in nodes:
                node_to_ps[n].append(ps)

        # ── 4. Orphan Nodes ────────────────────────────────────────────────
        expected_row = session.run("""
            MATCH (n:Node {pid_id: $pid_id})
            WHERE NOT (n)<-[:CONTAINS]-(:PipeSegment {pid_id: $pid_id})
              AND coalesce(n.structural_type, 'UNKNOWN') IN ['SYMBOL', 'BOUNDARY']
            RETURN collect(n.id) AS ids, count(n) AS cnt
        """, pid_id=pid_id).single()

        unexpected_row = session.run("""
            MATCH (n:Node {pid_id: $pid_id})
            WHERE NOT (n)<-[:CONTAINS]-(:PipeSegment {pid_id: $pid_id})
              AND coalesce(n.structural_type, 'UNKNOWN') IN ['CONNECTOR', 'UNKNOWN']
            RETURN collect(n.id) AS ids, count(n) AS cnt
        """, pid_id=pid_id).single()

        expected_cnt   = expected_row["cnt"]   if expected_row   else 0
        unexpected_cnt = unexpected_row["cnt"] if unexpected_row else 0

        summary["orphan_nodes"]           = expected_cnt + unexpected_cnt
        summary["expected_orphan_nodes"]  = expected_cnt
        summary["unexpected_orphan_nodes"] = unexpected_cnt

        if expected_row and expected_row.get("ids"):
            diagnostics.append({"type": "expected_orphans", "ids": expected_row["ids"]})
        if unexpected_row and unexpected_row.get("ids"):
            diagnostics.append({"type": "unexpected_orphans", "ids": unexpected_row["ids"]})

        # ── 5. Duplicate membership ────────────────────────────────────────
        nodes_in_multips = {
            n: ps for n, ps in node_to_ps.items() if len(ps) > 1
        }
        summary["nodes_in_multips"] = len(nodes_in_multips)

        # ── 6. Optional PS adjacency ───────────────────────────────────────
        ps_adj_set = set()
        if allow_ps_adjacency:
            adj_rows = session.run("""
                MATCH (a:PipeSegment)-[:JOINS_AT|LINKS_TO]-(b:PipeSegment)
                RETURN DISTINCT a.id AS a, b.id AS b
            """).data()
            for r in adj_rows:
                if r["a"] and r["b"] and r["a"] != r["b"]:
                    ps_adj_set.add(tuple(sorted((r["a"], r["b"]))))

        # ── 7. Node PIPE adjacency  (was CONNECTED) ────────────────────────
        conn_rows = session.run("""
            MATCH (n1:Node {pid_id: $pid_id})-[:PIPE]-(n2:Node {pid_id: $pid_id})
            RETURN DISTINCT n1.id AS a, n2.id AS b
        """, pid_id=pid_id).data()

        node_adj   = defaultdict(set)
        conn_pairs = []

        for r in conn_rows:
            if r["a"] is None or r["b"] is None:
                continue
            node_adj[r["a"]].add(r["b"])
            node_adj[r["b"]].add(r["a"])
            conn_pairs.append((r["a"], r["b"]))

        # ── 8. Bypass detection ────────────────────────────────────────────
        for n1, n2 in conn_pairs:
            ps1 = node_to_ps.get(n1)
            ps2 = node_to_ps.get(n2)

            if not ps1 or not ps2:
                diagnostics.append({
                    "type": "membership_missing",
                    "n1": n1, "n2": n2,
                    "ps1": ps1, "ps2": ps2,
                })
                continue

            if set(ps1) & set(ps2):
                continue

            if allow_ps_adjacency:
                if any(
                    tuple(sorted((a, b))) in ps_adj_set
                    for a in ps1 for b in ps2
                ):
                    continue

            summary["bypass_errors"] += 1
            diagnostics.append({
                "type": "bypass",
                "n1": n1, "n2": n2,
                "ps1": ps1, "ps2": ps2,
            })

        # ── 9. Internal connectivity ───────────────────────────────────────
        for ps, nodes in ps_to_nodes.items():
            if len(nodes) <= 1:
                continue

            start      = nodes[0]
            reachable  = bfs_connected(set(nodes), node_adj, start)
            unreachable = sorted(set(nodes) - reachable)

            if unreachable:
                summary["internal_disconnected"] += 1
                diagnostics.append({
                    "type": "internal_disconnected",
                    "pipe_segment": ps,
                    "reachable_count": len(reachable),
                    "unreachable_nodes": unreachable,
                })

    # ── 10. CSV output ─────────────────────────────────────────────────────
    if write_csv and diagnostics:
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        all_fields = set()
        for d in diagnostics:
            all_fields.update(d.keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(all_fields))
            writer.writeheader()
            writer.writerows(diagnostics)

    print("===================================================")
    print(f"[VALIDATE] PipeSegments scanned      : {summary['total_pipe_segments']}")
    print(f"[VALIDATE] Orphan nodes (total)      : {summary['orphan_nodes']} "
          f"(expected={summary.get('expected_orphan_nodes', 0)} "
          f"unexpected={summary.get('unexpected_orphan_nodes', 0)})")
    print(f"[VALIDATE] Nodes in multiple PS      : {summary['nodes_in_multips']}")
    print(f"[VALIDATE] Dead-end PipeSegments     : {summary['dead_end']}")
    print(f"[VALIDATE] Isolated PipeSegments     : {summary['isolated']}")
    print(f"[VALIDATE] Bypass errors             : {summary['bypass_errors']}")
    print(f"[VALIDATE] Internal disconnected PS  : {summary['internal_disconnected']}")
    print("===================================================")
    print(f"[VALIDATE] Completed in {time.time() - start_ts:.2f}s")

    return summary