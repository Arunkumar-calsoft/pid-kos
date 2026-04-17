// ============================================================================
// Question 10.9 — 10. External Interfaces
// Engineer question: "Which external interfaces are annotated as outlets?"
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {role:'outlet', pid_id:$pid_id}) RETURN e.equipment_id, e.direction
LIMIT 50
