// ============================================================================
// Question 18.6 — 18. Isolation & Reachability
// Engineer question: "Which valves cannot reach any inlet/outlet?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id}) WHERE NOT EXISTS {(v)-[:PIPE*1..30]-(:Node {label:'inlet/outlet'})} RETURN v.id
LIMIT 50
