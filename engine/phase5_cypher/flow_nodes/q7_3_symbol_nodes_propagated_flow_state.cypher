// ============================================================================
// Question 7.3 — 7. Node-Level Flow State
// Engineer question: "Show all SYMBOL nodes with PROPAGATED flow state."
//
// Operation: list
// Required keywords: propagated
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {structural_type:'SYMBOL', flow_state:'PROPAGATED', pid_id:$pid_id}) RETURN n.id, n.label, n.flow_confidence
LIMIT 50
