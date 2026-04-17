// ============================================================================
// Question 10.2 — 10. External Interfaces
// Engineer question: "Show all inlet/outlet interface node IDs and positions."
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id}) RETURN n.id, n.xmin, n.ymin, n.xmax, n.ymax
LIMIT 50
