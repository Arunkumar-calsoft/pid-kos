# engine/phase1_segmentation/link_pipe_segments.py
#
# Phase 1 — Diagnostic utility: PipeSegment connectivity reporter.
#
# GAP-11 FIX:
#   Original had two problems:
#   1. database="kos" hardcoded — wrong database name, always failed silently.
#   2. No pid_id scoping — queried ALL PipeSegments from ALL PIDs, producing
#      meaningless mixed-PID output when multiple PIDs exist in the database.
#
#   Fixed: pid_id is now a required argument. All queries are scoped to pid_id.
#   database is passed in from the caller (Neo4jLoader.database) rather than
#   hardcoded. Caller pattern matches run_phase1.py / validate_segments.py.
#
# USAGE:
#   Called as a diagnostic tool from run_phase1.py or standalone:
#       from engine.phase1_segmentation.link_pipe_segments import link_pipe_segments
#       link_pipe_segments(driver, database=loader.database, pid_id='PID_2')

def link_pipe_segments(driver, database: str, pid_id: str) -> dict:
    """
    Diagnostic utility: reports connectivity and reasoning traces for
    PipeSegments belonging to a specific PID.

    Does NOT create any new semantics or relationships.

    Args:
        driver:   Neo4j driver instance
        database: Neo4j database name (e.g. 'chatbot')
        pid_id:   PID identifier — required for scoping

    Returns:
        dict with summary counts:
          total_ps, connected_ps, full_trace_ps, unconnected_ps
    """
    if not pid_id:
        raise ValueError("[link_pipe_segments] pid_id is required")

    with driver.session(database=database) as session:

        # Fetch all PipeSegments for this PID
        ps_rows = session.run(
            "MATCH (ps:PipeSegment {pid_id: $pid_id}) RETURN ps.id AS id ORDER BY ps.id",
            pid_id=pid_id,
        ).data()

        total_ps       = len(ps_rows)
        connected_ps   = 0
        full_trace_ps  = 0

        print("===================================================")
        print(f"[INFO] PID={pid_id} | Total PipeSegments: {total_ps}")
        print("===================================================")

        for r in ps_rows:
            ps_id = r["id"]

            joins = session.run(
                """
                MATCH (ps:PipeSegment {id: $id, pid_id: $pid_id})-[r:JOINS_AT]-(other:PipeSegment {pid_id: $pid_id})
                RETURN other.id AS neighbor, r.kind AS kind, r.trace_nodes AS trace
                """,
                id=ps_id, pid_id=pid_id,
            ).data()

            if joins:
                connected_ps += 1

                print(f"[PipeSegment] {ps_id} connected to {len(joins)} segments")
                for j in joins[:5]:
                    print(
                        f"   -> {j['neighbor']} | kind={j['kind']} | trace={j['trace']}"
                    )
                if len(joins) > 5:
                    print(f"   ... {len(joins) - 5} more joins")

                if all(j.get("trace") for j in joins):
                    full_trace_ps += 1
            else:
                print(f"[PipeSegment] {ps_id} has NO joins")

        # LPS adjacency count for this PID
        lps_adj = session.run(
            """
            MATCH (a:LogicalPipeSegment {pid_id: $pid_id})-[r:ADJACENT_VIA_NODES]-(b:LogicalPipeSegment {pid_id: $pid_id})
            RETURN count(DISTINCT r) AS adj_count,
                   count(DISTINCT a) AS lps_count
            """,
            pid_id=pid_id,
        ).single()
        adj_count = int(lps_adj["adj_count"]) if lps_adj else 0
        lps_count = int(lps_adj["lps_count"]) if lps_adj else 0

        print("===================================================")
        print(f"[SUMMARY] PID                        : {pid_id}")
        print(f"[SUMMARY] Total PipeSegments         : {total_ps}")
        print(f"[SUMMARY] Connected PipeSegments     : {connected_ps}")
        print(f"[SUMMARY] Fully traced PS             : {full_trace_ps}")
        print(f"[SUMMARY] Unconnected PS              : {total_ps - connected_ps}")
        print(f"[SUMMARY] PS missing trace_nodes      : {connected_ps - full_trace_ps}")
        print(f"[SUMMARY] LPS (this PID)              : {lps_count}")
        print(f"[SUMMARY] ADJACENT_VIA_NODES edges    : {adj_count}")
        if lps_count > 0 and adj_count == 0:
            print(f"[WARN] 0 adjacency edges for {lps_count} LPS — Phase 4 FSM will fail!")
        print("===================================================")

        return {
            "total_ps":      total_ps,
            "connected_ps":  connected_ps,
            "full_trace_ps": full_trace_ps,
            "unconnected_ps": total_ps - connected_ps,
            "lps_count":     lps_count,
            "adj_edges":     adj_count,
        }