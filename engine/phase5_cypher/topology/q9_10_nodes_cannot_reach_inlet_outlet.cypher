// ============================================================================
// Question 9.10 — 9. Connectivity & Topology
// Engineer question: "Which nodes cannot reach any inlet/outlet?"
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {structural_type:'SYMBOL', pid_id:$pid_id}) WHERE NOT (n.label IN ['inlet/outlet','background','arrow']) AND NOT EXISTS {(n)-[:PIPE*1..30]-(:Node {label:'inlet/outlet'})} RETURN n.id, n.label
LIMIT 50
