// ============================================================================
// Question 7.6 — 7. Node-Level Flow State
// Engineer question: "Which tanks have SEEDED flow state?"
//
// Operation: list
// Required keywords: seeded
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'tank', flow_state:'SEEDED', pid_id:$pid_id}) RETURN n.id, n.flow_direction, n.flow_confidence
LIMIT 50
