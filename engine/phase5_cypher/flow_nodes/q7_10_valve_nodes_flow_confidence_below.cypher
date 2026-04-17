// ============================================================================
// Question 7.10 — 7. Node-Level Flow State
// Engineer question: "Which valve nodes have flow confidence below 0.5?"
//
// Operation: list
// Required keywords: confidence, below
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'valve', pid_id:$pid_id}) WHERE n.flow_confidence IS NOT NULL AND n.flow_confidence < 0.5 RETURN n.id, n.flow_confidence
LIMIT 50
