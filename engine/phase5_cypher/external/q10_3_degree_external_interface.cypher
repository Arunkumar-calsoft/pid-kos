// ============================================================================
// Question 10.3 — 10. External Interfaces
// Engineer question: "What is the degree of each external interface?"
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id}) RETURN n.id, size([(n)-[:PIPE]-() |1]) AS degree
LIMIT 50
