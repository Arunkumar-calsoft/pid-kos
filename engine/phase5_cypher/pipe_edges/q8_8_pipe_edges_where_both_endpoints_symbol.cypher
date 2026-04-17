// ============================================================================
// Question 8.8 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Show PIPE edges where both endpoints are SYMBOL nodes."
//
// Operation: list
// Required keywords: symbol, endpoint
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Node {structural_type:'SYMBOL', pid_id:$pid_id})-[r:PIPE]->(b:Node {structural_type:'SYMBOL', pid_id:$pid_id}) RETURN a.id, a.label, b.id, b.label
LIMIT 50
