// ============================================================================
// Question 6.11 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show all Evidence nodes with their observed direction and confidence."
//
// Operation: list
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {pid_id:$pid_id}) RETURN e.id, e.observed_direction, e.confidence, e.source ORDER BY e.confidence DESC
LIMIT 50
