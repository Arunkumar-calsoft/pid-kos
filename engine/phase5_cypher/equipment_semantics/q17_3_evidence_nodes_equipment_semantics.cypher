// ============================================================================
// Question 17.3 — 17. Equipment Semantics
// Engineer question: "Show all Evidence nodes from equipment semantics."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {source:'phase3_equipment_semantics', pid_id:$pid_id}) RETURN e.id, e.equipment_id, e.role, e.direction, e.confidence
LIMIT 50
