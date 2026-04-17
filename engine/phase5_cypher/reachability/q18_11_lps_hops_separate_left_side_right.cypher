// ============================================================================
// Question 18.11 — 18. Isolation & Reachability
// Engineer question: "How many LPS-hops separate left-side from right-side interfaces?"
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (left:Node {pid_id: $pid_id, label: 'inlet/outlet'})
WHERE left.xmin < 500
MATCH (right:Node {pid_id: $pid_id, label: 'inlet/outlet'})
WHERE right.xmin > 1500
MATCH (left)-[:ENDPOINT_OF]->(lps_l:LogicalPipeSegment)
MATCH (right)-[:ENDPOINT_OF]->(lps_r:LogicalPipeSegment)
MATCH path = shortestPath((lps_l)-[:ADJACENT_VIA_NODES*..30]-(lps_r))
RETURN left.id AS left_interface, right.id AS right_interface,
       length(path) AS lps_hops
ORDER BY lps_hops ASC
LIMIT 50
