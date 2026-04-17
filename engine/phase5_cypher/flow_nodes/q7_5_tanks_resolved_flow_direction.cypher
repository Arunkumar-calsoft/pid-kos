// ============================================================================
// Question 7.5 — 7. Node-Level Flow State
// Engineer question: "Show all tanks with resolved flow direction."
//
// Operation: list
// Required keywords: tank
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'tank', pid_id:$pid_id}) WHERE n.flow_direction IS NOT NULL RETURN n.id, n.flow_direction, n.flow_confidence
LIMIT 50
