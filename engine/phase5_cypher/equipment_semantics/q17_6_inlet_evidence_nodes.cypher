// ============================================================================
// Question 17.6 — 17. Equipment Semantics
// Engineer question: "Show inlet Evidence nodes."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {role:'inlet', pid_id:$pid_id}) RETURN e.id, e.equipment_id, e.direction, e.confidence
LIMIT 50
