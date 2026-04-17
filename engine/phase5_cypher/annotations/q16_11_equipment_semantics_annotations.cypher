// ============================================================================
// Question 16.11 — 16. Annotation Triage & Metadata
// Engineer question: "Show all equipment_semantics annotations."
//
// Operation: list
// Required keywords: semantics, equipment
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {intent:'equipment_semantics', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.equipment_id
LIMIT 50
