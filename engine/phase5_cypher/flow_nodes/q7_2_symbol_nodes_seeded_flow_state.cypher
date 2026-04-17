// ============================================================================
// Question 7.2 — 7. Node-Level Flow State
// Engineer question: "Show all SYMBOL nodes with SEEDED flow state."
//
// Operation: list
// Required keywords: seeded
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {structural_type:'SYMBOL', flow_state:'SEEDED', pid_id:$pid_id}) RETURN n.id, n.label, n.flow_direction, n.flow_confidence
LIMIT 50
