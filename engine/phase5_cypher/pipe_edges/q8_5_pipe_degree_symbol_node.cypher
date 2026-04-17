// ============================================================================
// Question 8.5 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Show PIPE degree for every SYMBOL node."
//
// Operation: list
// Required keywords: degree, symbol
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {structural_type:'SYMBOL', pid_id:$pid_id}) RETURN n.id, n.label, size([(n)-[:PIPE]-() |1]) AS pipe_degree ORDER BY pipe_degree DESC
LIMIT 50
