// ============================================================================
// Question 7.7 — 7. Node-Level Flow State
// Engineer question: "Show all nodes where flow was assigned by equipment semantics."
//
// Operation: list
// Required keywords: semantics
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {flow_source:'phase4_equipment_assignment', pid_id:$pid_id}) RETURN n.id, n.label, n.flow_direction
LIMIT 50
