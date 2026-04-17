import yaml
from neo4j import GraphDatabase

cfg = yaml.safe_load(open("config/neo4j.yaml"))["neo4j"]
driver = GraphDatabase.driver(cfg["uri"], auth=(cfg["user"], cfg["password"]))
with driver.session(database=cfg["database"]) as s:
    # Full picture of tank4 and its pipe segments
    print("=== tank4 LPS details ===")
    rows = s.run("""
MATCH (n:Node {id:'tank4'})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
RETURN lps.id AS lps_id, lps.flow_state AS fs, lps.flow_direction AS fd,
       lps.flow_confidence AS conf, lps.seed_confidence AS seed_conf
""").data()
    for r in rows:
        print(r)

    # Check Evidence for tank4's LPS
    print("\n=== Evidence on tank4 LPS ===")
    rows2 = s.run("""
MATCH (n:Node {id:'tank4'})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
OPTIONAL MATCH (e:Evidence)-[:ABOUT]->(lps)
RETURN lps.id AS lps_id, e.observed_direction AS ev_dir,
       e.pixel_direction AS pix_dir, e.direction_method AS method,
       e.confidence AS conf, e.source AS src
""").data()
    for r in rows2:
        print(r)

    # Check adjacent LPS to tank4 + their flow directions
    print("\n=== Neighbours of tank4 LPS ===")
    rows3 = s.run("""
MATCH (n:Node {id:'tank4'})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)
MATCH (lps)-[:ADJACENT_VIA_NODES]-(nb:LogicalPipeSegment)
RETURN lps.id AS lps_id, nb.id AS nb_id, nb.flow_state AS nb_fs, nb.flow_direction AS nb_fd
LIMIT 20
""").data()
    for r in rows3:
        print(r)

    # Verify the fixed query works now
    print("\n=== Fixed downstream query (FORWARD) ===")
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
  AND NOT far.label IN ['crossing','arrow']
RETURN DISTINCT far.id AS node_id, far.label AS type,
       lps.id AS via_segment, lps.flow_state AS flow_state
ORDER BY far.label, far.id
LIMIT 50
        """).data()
        print(f"FORWARD rows: {len(rows4)}")
        for r in rows4[:5]:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")

    # Try REVERSE (upstream of tank4)
    print("\n=== Fixed REVERSE query (upstream of tank4) ===")
    try:
        rows5 = s.run("""
MATCH (start:Node {id: 'tank4'})-[:ENDPOINT_OF]->(lps0:LogicalPipeSegment)
WHERE lps0.flow_state IN ['SEEDED','PROPAGATED']
  AND lps0.flow_direction = 'REVERSE'
MATCH (lps0)-[:ADJACENT_VIA_NODES*0..8]-(lps:LogicalPipeSegment)
WHERE lps.flow_direction = 'REVERSE'
  AND lps.flow_state IN ['SEEDED','PROPAGATED']
MATCH (far:Node)-[:ENDPOINT_OF]->(lps)
WHERE far.id <> start.id
  AND far.structural_type = 'SYMBOL'
  AND NOT far.label IN ['crossing','arrow']
RETURN DISTINCT far.id AS node_id, far.label AS type,
       lps.id AS via_segment, lps.flow_state AS flow_state
ORDER BY far.label, far.id
LIMIT 50
        """).data()
        print(f"REVERSE rows: {len(rows5)}")
        for r in rows5[:10]:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")

driver.close()
