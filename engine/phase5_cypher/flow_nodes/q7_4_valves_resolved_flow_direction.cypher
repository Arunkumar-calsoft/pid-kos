// ============================================================================
// Question 7.4 — 7. Node-Level Flow State
// Engineer question: "Show all valves with resolved flow direction."
//
// Operation: list
// Required keywords: valve
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'valve', pid_id:$pid_id}) WHERE n.flow_direction IS NOT NULL RETURN n.id, n.flow_direction, n.flow_state, n.flow_confidence
LIMIT 50
