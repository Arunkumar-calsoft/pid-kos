// ============================================================================
// Question 17.7 — 17. Equipment Semantics
// Engineer question: "Show outlet Evidence nodes."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {role:'outlet', pid_id:$pid_id}) RETURN e.id, e.equipment_id, e.direction, e.confidence
LIMIT 50
