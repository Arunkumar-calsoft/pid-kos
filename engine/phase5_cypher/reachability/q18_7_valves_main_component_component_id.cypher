// ============================================================================
// Question 18.7 — 18. Isolation & Reachability
// Engineer question: "Which valves are in the main component (component_id=0)?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps:PipeSegment {component_id:0, pid_id:$pid_id})-[:CONTAINS]->(n:Node {label:'valve', pid_id:$pid_id}) RETURN DISTINCT n.id
LIMIT 50
