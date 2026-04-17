// ============================================================================
// Question 18.2 — 18. Isolation & Reachability
// Engineer question: "Show all isolated nodes."
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.label<>'background' AND size([(n)-[:PIPE]-() |1])=0 RETURN n.id, n.label
LIMIT 50
