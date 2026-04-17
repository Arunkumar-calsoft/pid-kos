// ============================================================================
// Question 10.8 — 10. External Interfaces
// Engineer question: "Which external interfaces are annotated as inlets?"
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {role:'inlet', pid_id:$pid_id}) WHERE e.source='phase3_equipment_semantics' RETURN e.equipment_id, e.equipment_label
LIMIT 50
