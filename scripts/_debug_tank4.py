import yaml
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
with driver.session(database=cfg["database"]) as s:
    # Check tank node IDs
    rows = s.run(
        "MATCH (n:Node) WHERE toLower(n.id) CONTAINS 'tank' OR toLower(n.label) CONTAINS 'tank' "
        "RETURN n.id, n.label, n.pid_id LIMIT 10"
    ).data()
    print("=== TANKS ===")
    for r in rows:
        print(r)

    # Check actual flow_state values
    print("\n=== FLOW STATES (LPS) ===")
    rows2 = s.run(
        "MATCH (l:LogicalPipeSegment) RETURN l.flow_state AS fs, count(*) AS n ORDER BY n DESC"
    ).data()
    for r in rows2:
        print(r)

    # Check tank4 specifically with ENDPOINT_OF
    print("\n=== tank4 ENDPOINT_OF ===")
    rows3 = s.run(
        "MATCH (n:Node) WHERE n.id = 'tank4' OR n.id = 'Tank4' OR n.id = 'TANK4' "
        "OPTIONAL MATCH (n)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment) "
        "RETURN n.id, n.label, n.pid_id, lps.id AS lps_id, lps.flow_state, lps.flow_direction"
    ).data()
    for r in rows3:
        print(r)

    # Run the failing query directly to get the real error
    print("\n=== DIRECT QUERY TEST ===")
    try:
        rows4 = s.run("""
MATCH (start:Node {id: 'tank4'})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)
WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']
  AND lps0.flow_direction = 'FORWARD'
MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)
WHERE lps.flow_direction = 'FORWARD'
  AND lps.flow_state IN ['SEEDED','PROPAGATED']
MATCH (far:Node)-[:ENDPOINT_OF]->(lps)
WHERE far.id <> start.id
  AND far.structural_type = 'SYMBOL'
  AND far.label NOT IN ['crossing','arrow']
RETURN DISTINCT far.id AS node_id, far.label AS type,
       lps.id AS via_segment,
       lps.flow_state AS flow_state,
       lps.flow_confidence AS confidence
ORDER BY far.label, far.id
LIMIT 50
        """).data()
        print(f"Success: {len(rows4)} rows")
        for r in rows4[:5]:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")

driver.close()
