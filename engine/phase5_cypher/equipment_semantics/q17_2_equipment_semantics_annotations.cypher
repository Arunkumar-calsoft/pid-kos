// ============================================================================
// Question 17.2 — 17. Equipment Semantics
// Engineer question: "Show all equipment semantics annotations."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {intent:'equipment_semantics', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.equipment_id, ann.target_id
LIMIT 50
