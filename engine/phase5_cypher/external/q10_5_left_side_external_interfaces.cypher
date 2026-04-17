// ============================================================================
// Question 10.5 — 10. External Interfaces
// Engineer question: "Show left-side external interfaces."
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id}) WHERE n.xmin < 500 RETURN n.id, n.xmin
LIMIT 50
