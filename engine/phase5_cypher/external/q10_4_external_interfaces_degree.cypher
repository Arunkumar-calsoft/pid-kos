// ============================================================================
// Question 10.4 — 10. External Interfaces
// Engineer question: "Are all external interfaces degree=1?"
//
// Operation: validate
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id}) WHERE size([(n)-[:PIPE]-() |1]) <> 1 RETURN count(*) AS total
