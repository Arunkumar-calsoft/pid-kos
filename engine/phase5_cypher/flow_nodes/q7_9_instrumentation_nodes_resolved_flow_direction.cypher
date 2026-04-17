// ============================================================================
// Question 7.9 — 7. Node-Level Flow State
// Engineer question: "Show all instrumentation nodes with resolved flow direction."
//
// Operation: list
// Required keywords: instrument
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'instrumentation', pid_id:$pid_id}) WHERE n.flow_direction IS NOT NULL RETURN n.id, n.flow_direction
LIMIT 50
