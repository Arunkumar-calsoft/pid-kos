// ============================================================================
// Question 2.13 — 2. Valve Placement & Connectivity
// Engineer question: "Show each valve's resolved flow direction (Node level)."
//
// Operation: list
// Required keywords: resolved, direction
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'valve', pid_id:$pid_id}) WHERE n.flow_direction IS NOT NULL RETURN n.id, n.flow_direction, n.flow_state, n.flow_confidence
LIMIT 50
