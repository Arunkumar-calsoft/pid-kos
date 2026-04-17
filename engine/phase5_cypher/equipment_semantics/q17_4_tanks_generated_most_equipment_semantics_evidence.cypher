// ============================================================================
// Question 17.4 — 17. Equipment Semantics
// Engineer question: "Which tanks generated the most equipment semantics evidence?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {equipment_label:'tank', pid_id:$pid_id}) RETURN e.equipment_id, count(*) AS n ORDER BY n DESC
