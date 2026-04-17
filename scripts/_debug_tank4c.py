import yaml
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
with driver.session(database=cfg["database"]) as s:
    # Test fixed downstream query for tank4
    print("=== DOWNSTREAM of tank4 (fixed query) ===")
    try:
        rows = s.run("""
MATCH (start:Node {id: 'tank4'})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)
WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']
  AND (
    (lps0.flow_direction = 'FORWARD' AND lps0.id STARTS WITH 'tank4__')
    OR
    (lps0.flow_direction = 'REVERSE' AND lps0.id ENDS WITH '__tank4')
  )
MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)
WHERE lps.flow_state IN ['SEEDED','PROPAGATED']
MATCH (far:Node)-[:ENDPOINT_OF]->(lps)
WHERE far.id <> start.id
  AND far.structural_type = 'SYMBOL'
  AND NOT far.label IN ['crossing','arrow']
RETURN DISTINCT far.id AS node_id, far.label AS type,
       lps.id AS via_segment, lps.flow_state AS flow_state
ORDER BY far.label, far.id
LIMIT 50
        """).data()
        print(f"Rows: {len(rows)}")
        for r in rows:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")

    # Test upstream of tank4
    print("\n=== UPSTREAM of tank4 (fixed query) ===")
    try:
        rows2 = s.run("""
MATCH (start:Node {id: 'tank4'})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)
WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']
  AND (
    (lps0.flow_direction = 'FORWARD' AND lps0.id ENDS WITH '__tank4')
    OR
    (lps0.flow_direction = 'REVERSE' AND lps0.id STARTS WITH 'tank4__')
  )
MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)
WHERE lps.flow_state IN ['SEEDED','PROPAGATED']
MATCH (far:Node)-[:ENDPOINT_OF]->(lps)
WHERE far.id <> start.id
  AND far.structural_type = 'SYMBOL'
  AND NOT far.label IN ['crossing','arrow']
RETURN DISTINCT far.id AS node_id, far.label AS type,
       lps.id AS via_segment, lps.flow_state AS flow_state
ORDER BY far.label, far.id
LIMIT 50
        """).data()
        print(f"Rows: {len(rows2)}")
        for r in rows2:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")

    # Test downstream of a node expected to have good downstream (tank67 on PID_0)
    print("\n=== DOWNSTREAM of tank67 (PID_0, smoke test) ===")
    tank67_lps = s.run(
        "MATCH (n:Node {id:'tank67'})-[:ENDPOINT_OF]->(lps) RETURN lps.id, lps.flow_state, lps.flow_direction"
    ).data()
    for r in tank67_lps:
        print(r)

driver.close()
