"""Diagnose tank70 graph structure."""
from agent.cli import build_agent
_, loader, _ = build_agent()
from agent.query_runner import QueryRunner
qr = QueryRunner(loader)

print("=== tank70 relationships ===")
for row in qr.run('MATCH (n:Node {id: "tank70"})-[r]-() RETURN type(r) AS rel_type, count(r) AS cnt ORDER BY cnt DESC'):
    print(row)

print("\n=== ENDPOINT_OF ===")
for row in qr.run('MATCH (n:Node {id: "tank70"})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment) RETURN lps.id, lps.flow_state, lps.flow_direction'):
    print(row)

print("\n=== PIPE neighbours ===")
for row in qr.run('MATCH (n:Node {id: "tank70"})-[:PIPE]-(nb:Node) RETURN nb.id AS nb, nb.label AS label LIMIT 10'):
    print(row)

print("\n=== PipeSegment contains tank70 ===")
for row in qr.run('MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node {id: "tank70"}) RETURN ps.id AS ps_id LIMIT 5'):
    print(row)

print("\n=== LPS via COVERS->PS->CONTAINS ===")
for row in qr.run('MATCH (ps:PipeSegment)-[:CONTAINS]->(n:Node {id: "tank70"}) MATCH (lps:LogicalPipeSegment)-[:COVERS]->(ps) RETURN lps.id, lps.flow_state, lps.flow_direction LIMIT 10'):
    print(row)

print("\n=== Downstream via PIPE traversal ===")
for row in qr.run("""
MATCH (start:Node {id: "tank70"})-[:PIPE*1..4]-(n:Node)
WHERE n.id <> "tank70" AND n.label <> 'background' AND n.label <> 'connector'
RETURN DISTINCT n.id AS node_id, n.label AS type
LIMIT 20
"""):
    print(row)
