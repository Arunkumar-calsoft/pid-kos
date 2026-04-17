// ============================================================================
// Question 6.12 — 6. Flow Direction & Arrow Evidence
// Engineer question: "Show Evidence nodes sourced from equipment semantics."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {source:'phase3_equipment_semantics', pid_id:$pid_id}) RETURN e.id, e.equipment_id, e.role, e.direction
LIMIT 50
