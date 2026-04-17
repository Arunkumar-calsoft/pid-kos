// ============================================================================
// Question 18.10 — 18. Isolation & Reachability
// Engineer question: "Which nodes are in the largest isolated component?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {pid_id:$pid_id})-[:CONTAINS]->(n:Node {pid_id:$pid_id}) WHERE ps.component_id = 90 OR ps.component_id = 99 RETURN ps.component_id, n.id, n.label
LIMIT 50
