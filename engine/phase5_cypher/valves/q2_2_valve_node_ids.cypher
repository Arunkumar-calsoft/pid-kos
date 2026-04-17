// ============================================================================
// Question 2.2 — 2. Valve Placement & Connectivity
// Engineer question: "List all valve node IDs."
//
// Operation: list
// Intent: valve_placement
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'valve', pid_id:$pid_id}) RETURN n.id
LIMIT 50
