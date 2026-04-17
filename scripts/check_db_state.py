"""Quick DB consistency check after overlapping pipeline runs."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader

loader = Neo4jLoader()
d = loader.driver
db = loader.database  # 'chatbot'
with d.session(database=db) as s:

    print("=== Labels in DB ===")
    for row in s.run("CALL db.labels() YIELD label RETURN label ORDER BY label"):
        print(f"  {row[0]}")

    print("\n=== Nodes per PID ===")
    for row in s.run("MATCH (n:Node) RETURN coalesce(n.pid_id,'(none)') AS pid, count(*) AS cnt ORDER BY pid"):
        print(f"  {row['pid']}: {row['cnt']}")

    print("\n=== LPS per PID ===")
    for row in s.run("MATCH (l:LogicalPipeSegment) RETURN coalesce(l.pid_id,'(none)') AS pid, count(*) AS cnt ORDER BY pid"):
        print(f"  {row['pid']}: {row['cnt']}")

    print("\n=== PID status ===")
    for row in s.run("MATCH (p:PID) RETURN p.pid_id, p.status ORDER BY p.pid_id"):
        print(f"  {row[0]}: {row[1]}")

    print("\n=== phase4_blocked LPS per PID ===")
    for row in s.run("MATCH (l:LogicalPipeSegment) WHERE l.phase4_blocked = true RETURN l.pid_id AS pid, count(*) AS cnt ORDER BY pid"):
        print(f"  {row['pid']}: {row['cnt']}")

    print("\n=== Flow states PID_2 ===")
    for row in s.run("MATCH (l:LogicalPipeSegment {pid_id:'PID_2'}) RETURN coalesce(l.flow_state,'null') AS state, count(*) AS cnt ORDER BY state"):
        print(f"  {row['state']}: {row['cnt']}")

    print("\n=== Equipment nodes with flow_pid_id != their own PID ===")
    rows = list(s.run("""
        MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
        WHERE n.pid_id <> lps.pid_id
        RETURN n.id, n.pid_id AS node_pid, lps.id, lps.pid_id AS lps_pid
        LIMIT 20
    """))
    if rows:
        for row in rows:
            print(f"  Node {row[0]}({row[1]}) -> LPS {row[2]}({row[3]})")
    else:
        print("  NONE — no cross-PID ENDPOINT_OF links")

    print("\n=== Contaminated equipment nodes (flow_pid_id != PID_2 but has PID_2 LPS) ===")
    rows = list(s.run("""
        MATCH (n:Node)
        WHERE n.flow_source = 'phase4_equipment_assignment'
          AND n.flow_pid_id IS NOT NULL
          AND n.flow_pid_id <> 'PID_2'
        MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:'PID_2'})
        RETURN n.id, n.pid_id, n.flow_pid_id, n.flow_direction
    """))
    print(f"  Found: {len(rows)}")
    for row in rows:
        print(f"  Node {row[0]} (pid={row[1]}, flow_pid={row[2]}, dir={row[3]})")

d.close()
print("\nDone.")

