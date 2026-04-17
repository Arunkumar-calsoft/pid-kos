"""Diagnose tank70 downstream accuracy."""
import logging
logging.disable(logging.CRITICAL)
from agent.cli import build_agent
_, loader, _ = build_agent()
from agent.query_runner import QueryRunner
qr = QueryRunner(loader)

print("=== LPS endpoints for tank70 ===")
for r in qr.run('MATCH (n:Node {id: "tank70"})-[:ENDPOINT_OF]->(lps:LogicalPipeSegment) RETURN lps.id, lps.flow_state, lps.flow_direction'):
    print(r)

print("\n=== Nodes on FORWARD LPS (general8__tank70) via COVERS->CONTAINS ===")
for r in qr.run('MATCH (lps:LogicalPipeSegment {id: "general8__tank70"})-[:COVERS]->(ps:PipeSegment)-[:CONTAINS]->(n:Node) WHERE n.structural_type = "SYMBOL" RETURN n.id, n.label'):
    print(r)

print("\n=== Other endpoints of general8__tank70 (not tank70) ===")
for r in qr.run('MATCH (ep:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {id: "general8__tank70"}) WHERE ep.id <> "tank70" RETURN ep.id, ep.label'):
    print(r)

print("\n=== Nodes on REVERSE LPS (general5__tank70) via COVERS->CONTAINS ===")
for r in qr.run('MATCH (lps:LogicalPipeSegment {id: "general5__tank70"})-[:COVERS]->(ps:PipeSegment)-[:CONTAINS]->(n:Node) WHERE n.structural_type = "SYMBOL" RETURN n.id, n.label'):
    print(r)

print("\n=== Other endpoints of general5__tank70 (not tank70) ===")
for r in qr.run('MATCH (ep:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {id: "general5__tank70"}) WHERE ep.id <> "tank70" RETURN ep.id, ep.label'):
    print(r)

print("\n=== All PIPE neighbours distance 1-3 from tank70 ===")
for r in qr.run("""
MATCH path = (start:Node {id: "tank70"})-[:PIPE*1..3]-(n:Node)
WHERE n.id <> "tank70" AND n.structural_type = 'SYMBOL'
RETURN DISTINCT n.id, n.label, length(path) AS hops
ORDER BY hops, n.id
"""):
    print(r)
