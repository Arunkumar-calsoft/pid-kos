// ============================================================================
// Question 18.9 — 18. Isolation & Reachability
// Engineer question: "Are all tanks reachable from all valves?"
//
// Operation: validate
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id})
OPTIONAL MATCH (v)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment)-[:ADJACENT_VIA_NODES*1..20]-(lps2:LogicalPipeSegment)<-[:ENDPOINT_OF]-(t:Node {label:'tank', pid_id:$pid_id})
RETURN v.id AS valve_id, count(DISTINCT t.id) AS reachable_tanks
ORDER BY reachable_tanks ASC
LIMIT 50
