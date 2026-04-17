// ============================================================================
// Question 10.6 — 10. External Interfaces
// Engineer question: "Show right-side external interfaces."
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id}) WHERE n.xmin > 1500 RETURN n.id, n.xmin
LIMIT 50
